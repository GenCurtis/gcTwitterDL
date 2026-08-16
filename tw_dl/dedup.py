# -*- coding: utf-8 -*-
# 内容级去重(md5 精确匹配):下载时判定「同用户/同别名组」的完全一致内容只保留时间戳最早的一份。
# - 范围:same_user + alias_group;跨组(cross)重复不删(可能是不同人巧合)
# - 保留规则:文件名前缀 %Y-%m-%d %H-%M + snowflake 推文ID 字典序即时间序,取最早
# - 只删「新下载的重复项」或「判定为较晚的副本」,从不删最早版本;索引原子写,损坏自动重建
import hashlib
import json
import os

from .logger import logger


class DedupIndex:
    """全局内容索引 {md5: [{user, file}]};原子落盘,损坏重建。
    首次使用(索引文件不存在)时全量扫描存量库建索引——否则增量下载判定不到已下载的旧文件。"""

    def __init__(self, root, alias, user):
        self.root = root
        self.alias = alias or {}
        self.user = user
        self.path = os.path.join(root, '_dedup_index.json')
        self.index = self._load()
        if not self.index:
            self._build_from_disk()

    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _build_from_disk(self):
        """全量扫描 downloads/{user}/* 媒体文件建索引(排除 csv/归档目录)"""
        built = 0
        for user in sorted(os.listdir(self.root)):
            udir = os.path.join(self.root, user)
            if not os.path.isdir(udir) or user.startswith('【已封号】'):
                continue
            for f in os.listdir(udir):
                if f.endswith('.csv'):
                    continue
                path = os.path.join(udir, f)
                try:
                    with open(path, 'rb') as fh:
                        digest = hashlib.md5(fh.read()).hexdigest()
                except OSError:
                    continue
                self.index.setdefault(digest, []).append({'user': user, 'file': f})
                built += 1
        if built:
            logger.info(f'内容去重索引已从存量库建立: {built} 个文件')
            self.persist()

    def persist(self):
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _related(self, user):
        """该 user 是否与当前用户构成去重关系(自己 或 同别名组)"""
        if user == self.user:
            return True
        my_group = next((g for g, ms in self.alias.items() if self.user in ms), None)
        return bool(my_group and user in self.alias.get(my_group, []))

    def decide(self, md5, filename):
        """下载完成后判定;返回 'keep'(登记/保留)或 'drop'(删除本次下载)。
        同 md5 且存在同用户/同组副本 → 保留时间戳最早的一份(字典序即时间序)。"""
        base = os.path.basename(filename)
        matches = self.index.get(md5, [])
        related = [m for m in matches if self._related(m['user'])]
        if not related:
            # 无重复(或仅跨组副本):登记,保留
            self.index[md5] = matches + [{'user': self.user, 'file': base}]
            self.persist()
            return 'keep'
        oldest = min([base] + [m['file'] for m in related])
        if base == oldest:
            # 本次下载的最早:删除库内较晚副本,保留新文件;
            # 同名同路径(重拉已下载内容)就是自己,无需删除也无日志
            dups = [m for m in related if not (m['file'] == base and m['user'] == self.user)]
            for m in dups:
                try:
                    os.remove(os.path.join(self.root, m['user'], m['file']))
                    logger.info(f'去重: 删除较晚副本 {m["user"]}/{m["file"]},保留最早版本 {self.user}/{base}')
                except OSError as e:
                    logger.warning(f'去重删除失败 {m["user"]}/{m["file"]}: {e}')
            self.index[md5] = [m for m in matches if m not in related] + [{'user': self.user, 'file': base}]
            self.persist()
            return 'keep'
        # 本次下载较晚:丢弃(不登记)
        logger.info(f'去重: {self.user}/{base} 与 {related[0]["user"]}/{related[0]["file"]} 内容相同,保留最早版本')
        self.persist()
        return 'drop'
