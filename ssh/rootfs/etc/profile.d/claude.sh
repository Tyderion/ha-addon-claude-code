# Claude Code ships a glibc ripgrep that does not run on musl (Alpine);
# use the system ripgrep package instead.
export USE_BUILTIN_RIPGREP=0
