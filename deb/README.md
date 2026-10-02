# Local DCP-o-matic package (optional)

By default, `docker build` downloads the DCP-o-matic command-line package from
[dcpomatic.com](https://dcpomatic.com/download).

If that download does not work for you (no internet access on the NAS, a
version that is not the default, another architecture...), download the
**Ubuntu 24.04 CLI** `.deb` yourself from
<https://dcpomatic.com/download>, put it in this folder and build again:
it will be installed instead.

`.deb` files in this folder are ignored by git.
