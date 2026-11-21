"""对象缓存与方案缓存。

按哈希存放已校验文件，离线更新可复用完整缓存的方案清单。
"""
import hashlib
import json
from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import atomic_json, read_json
from publish_switcher.sync.hashes import digest, hash_field
from publish_switcher.sync.manifests import validate_manifest


def _object(engine, entry):
    key = hash_field(entry)
    return engine.state / "objects" / (("git-" if key == "git_sha1" else "") + entry[key])



def cached(engine, entry, cancel=None):
    p = engine._object(entry)
    return (p.is_file() and not p.is_symlink() and p.stat().st_size == entry["size"]
            and digest(p, cancel, git=hash_field(entry) == "git_sha1") == entry[hash_field(entry)])



def save_profile(engine, manifest, source):
    validate_manifest(manifest)
    key = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    atomic_json(engine.state / "profiles" / (key + ".json"),
                {"manifest": manifest, "source": source.descriptor()})
    return key



def profiles(engine):
    result = []
    for path in sorted((engine.state / "profiles").glob("*.json")):
        try:
            data = read_json(path)
            validate_manifest(data["manifest"])
            result.append(data)
        except (OSError, ValueError, KeyError, SyncError):
            continue
    return result

