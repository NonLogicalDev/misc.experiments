# Historical INSV source patches

Both patches apply to `https://github.com/OpenSpeleo/insta360-rs` commit `b4f3845feb105b70c1928ed4316fe1d8a963bc36`. They preserve earlier, distinct experimental source projections; the maintained observation layer remains under `vendor/insta360-rs`.

| Patch | Former projection commit | Git tree | SHA-256 |
| --- | --- | --- | --- |
| `observation-previous.patch` | `78b8f55262eccac4e84d3fd16119bcb93c7e27fd` | `d251cef540eeebcf488dcb46bf44499384d35ed9` | `4be9576ba5b86bab45f18da19f466d71d31ff2ad7481f82487f22919bfed41ed` |
| `alignment-previous.patch` | `c3793870c44393ebc48cc6104742fd482b87735d` | `ca79ff0585d2c9943a444becd0f6832211c9e0b1` | `580b6fbe63913b5bb7c96f21081154ffb4e648e6006eaccca23e5f358b271c5e` |

On 2026-11-16, each patch was applied independently to an archive of the pinned commit and the result was recursively byte-compared to the corresponding former projection, excluding its `.git` directory; no differences were found. The patches preserve source trees, not original commit metadata, build products, or binary equivalence. The previous binary extensions have different hashes and remain preserved.

The former unversioned `/private/tmp/spheredim-spirula-release-src` recursively matched a fresh archive of pinned Spirula Studio commit `667e353bca3941303a4d93e93aa8ae3f2c202712`, tree `f2efac493ece5bc90a5c96340ce100464e10c54a`; no source differences needed archiving.
