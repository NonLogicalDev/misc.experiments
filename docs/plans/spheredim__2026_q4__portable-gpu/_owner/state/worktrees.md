# Checkout recovery

- Main project: `/Users/nonlogical/Projects/local/active/app.spheredim`; no root Git repository. The portable layer definition is the nested Git repository `vendor/360dvo-port/layers`, checkpoint `48a5d23575111033bb40c341092f42bb75e240c9`; its vendored upstream commit is `46f5ed0735d39aff29a75f28c360600340879b35`. The installed projection and environment are in `vendor/360dvo-port/work/`.
- The former staging checkout had checkpoint `1b56365260b94df484d99d6baa2327e60fb3e412`; its patch was verified byte-for-byte against the project layer before staging cleanup. Reconstruct from the project layer definition and vendored upstream archive.
- The vendored runtime is macOS arm64 only. AMD ROCm runtime packaging and hardware validation remain open. [Plan](../../theme-001-portable-tracking/active/plan-01%20Portable%20360DVO.md).
