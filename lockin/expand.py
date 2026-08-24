"""Expand rule hostnames with common subdomains and known aliases."""

GENERIC_PREFIXES = ("m", "mobile", "old", "new", "i", "www2")

# Bidirectional product aliases. No URL shorteners (t.co, lnkd.in).
ALIASES: dict[str, tuple[str, ...]] = {
    "youtube.com": ("youtu.be", "m.youtube.com"),
    "youtu.be": ("youtube.com", "m.youtube.com"),
    "facebook.com": ("fb.com", "m.facebook.com"),
    "fb.com": ("facebook.com", "m.facebook.com"),
    "instagram.com": ("instagr.am",),
    "instagr.am": ("instagram.com",),
    "reddit.com": ("old.reddit.com", "new.reddit.com", "i.reddit.com"),
    "twitter.com": ("x.com",),
    "x.com": ("twitter.com",),
    "tiktok.com": ("vm.tiktok.com",),
    "vm.tiktok.com": ("tiktok.com",),
}


def _bare(host: str) -> str:
    """Strip www and generic prefixes so expand() is idempotent."""
    h = host.strip().lower().rstrip(".")
    while h:
        if h.startswith("www."):
            h = h[4:]
            continue
        stripped = False
        for prefix in GENERIC_PREFIXES:
            p = prefix + "."
            if h.startswith(p):
                h = h[len(p) :]
                stripped = True
                break
        if not stripped:
            break
    return h


def expand(domains: list[str]) -> list[str]:
    """Return sorted unique hostnames including aliases and leak subdomains."""
    seeds: set[str] = set()
    for raw in domains:
        bare = _bare(raw)
        if bare:
            seeds.add(bare)

    changed = True
    while changed:
        changed = False
        for seed in list(seeds):
            for extra in ALIASES.get(seed, ()):
                bare = _bare(extra)
                if bare and bare not in seeds:
                    seeds.add(bare)
                    changed = True

    out = set(seeds)
    for seed in seeds:
        for prefix in GENERIC_PREFIXES:
            out.add(f"{prefix}.{seed}")
    return sorted(out)
