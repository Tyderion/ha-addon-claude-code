# Claude Code ships a glibc ripgrep that does not run on musl (Alpine);
# use the system ripgrep package instead.
export USE_BUILTIN_RIPGREP=0

# `claude doctor` warns unless the native install dir is on PATH. Append it:
# /usr/local/bin must stay first, so the add-on's `claude` wrapper (which pins
# the session name) wins over the binary it wraps.
case ":${PATH}:" in
    *:/root/.local/bin:*) ;;
    *) export PATH="${PATH}:/root/.local/bin" ;;
esac
