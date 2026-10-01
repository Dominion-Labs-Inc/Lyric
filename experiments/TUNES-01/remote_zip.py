"""Read members of a remote ZIP (ZIP64 included) with HTTP range requests."""
import struct, zlib, urllib.request, json, sys

URL = "https://huggingface.co/datasets/dadinghh2/HumTrans/resolve/main/all_wav.zip"

def fetch(start, end):
    req = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}", "User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def total_size():
    req = urllib.request.Request(URL, headers={"Range": "bytes=0-0", "User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Range"].split("/")[1])

def central_directory():
    size = total_size()
    tail = fetch(size - 65536 - 22, size - 1)
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_off = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    loc = tail.rfind(b"PK\x06\x07")
    if loc != -1:
        (z64_off,) = struct.unpack("<Q", tail[loc + 8:loc + 16])
        z64 = fetch(z64_off, z64_off + 56 - 1)
        cd_size, cd_off = struct.unpack("<QQ", z64[40:56])
    cd = fetch(cd_off, cd_off + cd_size - 1)
    entries, i = [], 0
    while i < len(cd) and cd[i:i + 4] == b"PK\x01\x02":
        (method, csize, usize, nlen, xlen, clen, off) = (
            struct.unpack("<H", cd[i + 10:i + 12])[0], *struct.unpack("<II", cd[i + 20:i + 28]),
            *struct.unpack("<HHH", cd[i + 28:i + 34]), struct.unpack("<I", cd[i + 42:i + 46])[0])
        name = cd[i + 46:i + 46 + nlen].decode("utf-8", "replace")
        extra = cd[i + 46 + nlen:i + 46 + nlen + xlen]
        j = 0
        while j + 4 <= len(extra):
            hid, hlen = struct.unpack("<HH", extra[j:j + 4])
            if hid == 1:
                vals, k = extra[j + 4:j + 4 + hlen], 0
                if usize == 0xFFFFFFFF: usize = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
                if csize == 0xFFFFFFFF: csize = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
                if off == 0xFFFFFFFF: off = struct.unpack("<Q", vals[k:k + 8])[0]; k += 8
            j += 4 + hlen
        entries.append({"name": name, "method": method, "csize": csize, "usize": usize, "offset": off})
        i += 46 + nlen + xlen + clen
    return entries

def read_member(e):
    head = fetch(e["offset"], e["offset"] + 30 - 1)
    nlen, xlen = struct.unpack("<HH", head[26:30])
    start = e["offset"] + 30 + nlen + xlen
    data = fetch(start, start + e["csize"] - 1)
    return data if e["method"] == 0 else zlib.decompress(data, -15)

if __name__ == "__main__":
    es = central_directory()
    json.dump(es, open(sys.argv[1], "w"))
    print(len(es), "entries;", sum(e["usize"] for e in es) / 1e9, "GB")
