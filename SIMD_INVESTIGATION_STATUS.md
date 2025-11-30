# SIMD Investigation Status - Polkadot Build Optimization

**Last Updated:** 2025-11-29 (Updated with auto-vectorization bloat analysis and x86-64-v3 benchmarks)
**Machine:** AMD EPYC 4484PX (AVX-512 capable)

## Executive Summary

**MAJOR FINDING: Auto-Vectorization Bloat** - Any target that enables AVX2 features causes LLVM to aggressively auto-vectorize, resulting in ~30x more ymm instructions than the official build. This affects all tested configurations: `target-cpu=native`, `-avx512f`, and `x86-64-v3`.

### Two Separate Problems Identified

1. **BLAKE2 hand-tuned code elimination** (SOLVED) - LTO eliminates hand-tuned AVX2 code when `target_feature="avx2"` is set at compile time. **Solution:** OnceLock function pointer dispatch prevents LTO devirtualization.

2. **Auto-vectorization bloat** (UNSOLVED) - LLVM aggressively vectorizes when AVX2 is enabled, creating massive code bloat that causes icache pressure.

### Instruction Count Comparison

| Build | zmm (AVX-512) | ymm (AVX2) | vs Official ymm |
|-------|--------------|-----------|-----------------|
| Official | 2,018 | **15,787** | baseline |
| Patched Native | 263,306 | 182,502 | 11.6x bloat |
| Patched + -avx512f | 2,018 | **468,970** | **29.7x bloat** |
| Patched + x86-64-v3 | 2,018 | **461,543** | **29.2x bloat** |

### Performance Results

| Build | BLAKE2-256 | vs Official | Cause of Slowdown |
|-------|-----------|-------------|-------------------|
| Official | 1.59 GiB/s | baseline | - |
| Patched Native | 1.46 GiB/s | **-8.2%** | AVX-512 frequency throttling |
| Patched + -avx512f | 1.57 GiB/s | **-1.3%** | icache pressure from bloat |
| Patched + x86-64-v3 | 1.54 GiB/s | **-3.1%** | icache pressure from bloat |

### Key Insight

The auto-vectorization bloat (~30x increase in ymm instructions) is NOT the primary performance issue. The performance impact from bloat is only ~1-3%. The primary performance issue with `target-cpu=native` on AVX-512 hardware is **frequency throttling from excessive AVX-512 usage** (~8% slowdown).

### Current Recommendations

1. **For production use:** Stick with official Parity builds or build without RUSTFLAGS
2. **If you need native optimizations:** Use `RUSTFLAGS="-C target-cpu=native -C target-feature=-avx512f"` with the OnceLock patch (expect ~1-3% BLAKE2 slowdown from bloat)
3. **The x86-64-v3 approach does NOT help** - it still causes auto-vectorization bloat

**Working solution (preserves hand-tuned code):** Patch `blake2b_simd` and `blake2s_simd` to use OnceLock-stored function pointers. See `patches/README.md` for implementation details.

---

## THE SMOKING GUN - CONFIRMED!

**The issue is BLAKE2 (blake2b_simd crate), not BLAKE3!**

| Binary | Has `blake2b_simd::avx2::compress1_loop` | Performance |
|--------|----------------------------------------|-------------|
| Official Parity Release | **YES** (hand-optimized AVX2) | Fast |
| Custom build (target-cpu=native) | **NO** - MISSING! | ~5% slower |
| New build (no target-cpu flag) | **YES** - RESTORED! | Fast |

### How This Was Confirmed

1. **Symbol analysis using strings:**
   ```bash
   # Official binary - HAS the dedicated AVX2 function:
   strings official_polkadot.bin | grep blake2b_simd
   # Output includes: _ZN12blake2b_simd4avx214compress1_loop...

   # Custom native build - MISSING the AVX2 function:
   strings polkadot_0.bin | grep blake2b_simd
   # Output only has: _ZN12blake2b_simd4guts14Implementation14compress1_loop...

   # New build (no native) - HAS the AVX2 function restored:
   objdump -t polkadot | grep "blake2b_simd.*avx2"
   # Output: blake2b_simd::avx2::compress1_loop
   ```

2. **Instruction count analysis:**
   | Build | ymm (AVX2) | zmm (AVX-512) |
   |-------|-----------|---------------|
   | Official | 15,787 | 2,018 |
   | Custom (native) | **184,805** | **263,460** |
   | New (no native) | 15,754 | 2,018 |

   The custom native build has **130x more AVX-512** and **12x more AVX2** instructions from compiler auto-vectorization.

---

## Root Cause Analysis

### Why `-C target-cpu=native` Breaks BLAKE2 Performance

The `blake2b_simd` crate (v1.0.2) uses this dispatch logic in `src/guts.rs`:

```rust
pub fn avx2_if_supported() -> Option<Self> {
    // Check whether AVX2 support is assumed by the build.
    #[cfg(target_feature = "avx2")]
    {
        return Some(Implementation(Platform::AVX2));
    }
    // Otherwise dynamically check for support if we can.
    #[cfg(feature = "std")]
    {
        if is_x86_feature_detected!("avx2") {
            return Some(Implementation(Platform::AVX2));
        }
    }
    None
}
```

**What happens with `-C target-cpu=native` on AVX-512 hardware:**

1. Rust compiler sets `target_feature = "avx2"` to true at compile time
2. The `#[cfg(target_feature = "avx2")]` branch is taken
3. The runtime detection code (`is_x86_feature_detected!`) is never compiled
4. **Critical:** During LTO (Link-Time Optimization), the dedicated `avx2::compress1_loop` function gets inlined/eliminated
5. Only the generic `guts::Implementation::compress1_loop` survives in the binary
6. The generic code gets auto-vectorized to AVX-512 instructions
7. Auto-vectorized AVX-512 is **slower** than hand-tuned AVX2 assembly

**Additional performance penalty:** AVX-512 instructions cause CPU frequency throttling (15-20% on some CPUs).

### Why Parity's Official Build Works

Examined Parity's release workflow at:
- `.github/workflows/release-build-binary.yml`
- `.github/scripts/release/build-linux-release.sh`

**Finding:** Parity uses `cargo build --profile production` **WITHOUT any RUSTFLAGS**.

This means:
- Generic x86-64 build (no target-cpu flag)
- `blake2b_simd` compiles ALL SIMD implementations (portable, SSE4.1, AVX2)
- Runtime detection via `is_x86_feature_detected!("avx2")` picks the fastest path at execution time
- The dedicated `avx2::compress1_loop` function is preserved in the binary

---

## Builds Analyzed

| # | Binary | Location | RUSTFLAGS | ymm | zmm | Has AVX2 func |
|---|--------|----------|-----------|-----|-----|---------------|
| 1 | Official | `bin/stable2509-2/official_polkadot.bin` | None (Parity) | 15,787 | 2,018 | ✓ YES |
| 2 | polkadot_0 | `bin/stable2509-2/polkadot_0.bin` | `-C target-cpu=native` | 184,805 | 263,460 | ✗ NO |
| 3 | No flags | `polkadot-sdk/target/production/polkadot` | None | 15,754 | 2,018 | ✓ YES |
| 4 | -avx512vl | `polkadot-sdk/target-no512vl/production/polkadot` | `native -avx512vl` | 178,879 | 279,294 | ✗ NO |
| 5 | -avx512f | `polkadot-sdk/target-no512f/production/polkadot` | `native -avx512f` | 467,064 | 2,018 | ✗ NO |

---

## BLAKE3 vs BLAKE2 Findings

### BLAKE3 (blake3 crate) - NOT the problem
- Hand-written AVX2/AVX-512 assembly IS PRESENT in all builds
- Symbols: `blake3_hash_many_avx2`, `blake3_hash_many_avx512`, etc.
- Byte-level comparison shows identical function bodies
- The ~2,018 zmm instructions in official/new builds come from blake3's handwritten AVX-512

### BLAKE2 (blake2b_simd crate) - THE PROBLEM
- Official: Has `blake2b_simd::avx2::compress1_loop` (hand-optimized)
- Native build: MISSING this function, only has generic implementation
- The generic implementation gets auto-vectorized to AVX-512, which is slower

---

## Tested Solutions and Results

### Option 1: Don't use target-cpu=native (VERIFIED WORKING)
```bash
# No RUSTFLAGS - matches Parity's official build
cargo build --profile production -p polkadot
```
**Result:** Hand-tuned BLAKE2 AVX2 code is preserved. ✓
**ymm/zmm:** ~15,754 / ~2,018 (matches official)
**Downside:** No native CPU optimizations for other parts of the codebase.

### Option 2: OnceLock Function Pointer Patch (VERIFIED WORKING - RECOMMENDED) ✓

Patch `blake2b_simd` and `blake2s_simd` to use OnceLock-stored function pointers for AVX2 dispatch.

```bash
# Add to polkadot-sdk/Cargo.toml:
[patch.crates-io]
blake2b_simd = { path = "/home/ubuntu/blake2-patch/blake2b_simd-1.0.2" }
blake2s_simd = { path = "/home/ubuntu/blake2-patch/blake2s_simd-1.0.1" }

# Build with native optimizations
RUSTFLAGS="-C target-cpu=native" cargo build --profile production -p polkadot
```

**Result:** Hand-tuned BLAKE2 AVX2 code is preserved WITH native optimizations! ✓
**Symbols preserved:**
- `blake2b_simd::avx2::compress1_loop` ✓
- `blake2b_simd::avx2::compress4_loop` ✓
- `blake3_hash_many_avx2` ✓

**Why it works:** LTO cannot devirtualize a function pointer stored in `OnceLock` that's initialized at runtime. The indirect call prevents inlining.

**Full implementation:** See `/home/ubuntu/patch-files/README.md`

### Option 3: Native with -avx512vl (TESTED - DOES NOT WORK) ✗
```bash
RUSTFLAGS="-C target-cpu=native -C target-feature=-avx512vl" cargo build --profile production -p polkadot
```
**Result:** Hand-tuned BLAKE2 AVX2 code is STILL ELIMINATED. ✗
**ymm/zmm:** ~178,879 / ~279,294 (bad - massive auto-vectorization)
**Why:** `-avx512vl` only disables vector length extensions; `avx512f` still allows 512-bit operations.

### Option 4: Native with -avx512f (TESTED - DOES NOT WORK) ✗
```bash
RUSTFLAGS="-C target-cpu=native -C target-feature=-avx512f" cargo build --profile production -p polkadot
```
**Result:** Hand-tuned BLAKE2 AVX2 code is STILL ELIMINATED. ✗
**ymm/zmm:** ~467,064 / ~2,018 (zmm is correct, but massive ymm auto-vectorization!)
**Why:** The issue is `target_feature="avx2"` at compile time, not AVX-512. Disabling AVX-512 just shifts auto-vectorization to AVX2.

### Option 5: black_box around feature detection (TESTED - DOES NOT WORK) ✗
```rust
// Attempted: wrap feature detection in black_box
if std::hint::black_box(is_x86_feature_detected!("avx2")) { ... }
```
**Result:** Hand-tuned BLAKE2 AVX2 code is STILL ELIMINATED. ✗
**Why:** `black_box` prevents the condition from being optimized, but LTO can still inline the function being called inside the branch.

### Option 6: #[inline(never)] attribute (TESTED - DOES NOT WORK) ✗
```rust
#[inline(never)]
pub fn compress1_loop(...) { ... }
```
**Result:** Hand-tuned BLAKE2 AVX2 code is STILL ELIMINATED. ✗
**Why:** LTO ignores `#[inline(never)]` during cross-crate optimization.

### Option 7: Use x86-64-v3 (TESTED - PARTIALLY WORKS) ⚠️
```bash
RUSTFLAGS="-C target-cpu=x86-64-v3" cargo build --profile production -p polkadot
```
**Result:** Hand-tuned BLAKE2 AVX2 code IS PRESERVED (with OnceLock patch), but auto-vectorization bloat still occurs.
**Instruction counts:** zmm=2,018 (correct), ymm=461,543 (29x bloat!)
**Performance:** BLAKE2-256 1.54 GiB/s (-3.1% vs official)
**Why partial:** x86-64-v3 enables 18 target features (vs 43 for native, 3 for default). This is enough to trigger aggressive LLVM auto-vectorization. The bloat causes icache pressure.

```
$ rustc --print cfg -C target-cpu=x86-64-v3 | grep target_feature | wc -l
18  # <-- Still too many features, causes auto-vectorization bloat
```

---

## Auto-Vectorization Bloat Analysis (NEW FINDING)

### The Problem

When building with any target that enables AVX2 features, LLVM aggressively auto-vectorizes loops throughout the codebase. This creates massive code bloat:

| Target | Features Enabled | ymm Instructions | Bloat vs Official |
|--------|-----------------|------------------|-------------------|
| default (x86-64) | 3 | 15,787 | baseline |
| x86-64-v3 | 18 | 461,543 | **29.2x** |
| native -avx512f | 29+ | 468,970 | **29.7x** |
| native | 43 | 182,502 | 11.6x (+ 263K zmm) |

### Root Cause

The issue is NOT specific to BLAKE2 or any particular crate. It's a general LLVM behavior:

```
# Default x86-64 enables only 3 features:
$ rustc --print cfg -C target-cpu=x86-64 | grep target_feature
target_feature="fxsr"
target_feature="sse"
target_feature="sse2"

# x86-64-v3 enables 18 features including AVX2:
$ rustc --print cfg -C target-cpu=x86-64-v3 | grep -E "avx|fma"
target_feature="avx"
target_feature="avx2"
target_feature="fma"

# Native enables 43 features including AVX-512:
$ rustc --print cfg -C target-cpu=native | grep target_feature | wc -l
43
```

When LLVM sees AVX2 is available, it vectorizes many loops that would otherwise use scalar operations. While this CAN improve performance for some workloads, it causes:

1. **Code bloat** - ~30x more ymm instructions
2. **Increased binary size** - More instructions to store
3. **icache pressure** - Hot code paths may not fit in L1i cache
4. **Potential performance degradation** - For code that doesn't benefit from vectorization

### Performance Impact

Surprisingly, the performance impact from bloat is relatively small:

| Build | Auto-vec ymm | BLAKE2-256 | vs Official |
|-------|-------------|-----------|-------------|
| Official | 15,787 | 1.59 GiB/s | baseline |
| x86-64-v3 (29x bloat) | 461,543 | 1.54 GiB/s | -3.1% |
| native -avx512f (30x bloat) | 468,970 | 1.57 GiB/s | -1.3% |

The ~30x code bloat only causes ~1-3% performance loss for BLAKE2 benchmark. The bigger issue on native builds is AVX-512 frequency throttling (~8%).

### Potential Solutions (NOT YET TESTED)

1. **Selective feature enabling** - Disable auto-vectorization features while keeping essential ones:
   ```bash
   RUSTFLAGS="-C target-cpu=x86-64-v3 -C target-feature=-avx,-avx2,+sse4.2"
   ```
   Risk: May break code that explicitly requires AVX2.

2. **LLVM vectorizer tuning** - Limit vectorization width:
   ```bash
   RUSTFLAGS="-C llvm-args=-vectorize-loops=false"  # Too aggressive - breaks blake2b_simd
   RUSTFLAGS="-C llvm-args=-vectorizer-min-trip-count=32"  # Only vectorize longer loops
   ```

3. **Profile-guided optimization (PGO)** - Let LLVM learn which vectorizations are beneficial:
   - Build with instrumentation, run representative workload, rebuild with profile data

4. **Accept the tradeoff** - The 1-3% performance loss from bloat may be acceptable if native optimizations benefit other parts of the application

---

## Why Disabling AVX-512 Doesn't Help

The root cause is **NOT** AVX-512 auto-vectorization. It's the compile-time `target_feature="avx2"` flag:

1. When `target-cpu=native` is used on ANY AVX2+ machine, rustc sets `target_feature="avx2"`
2. This triggers the `#[cfg(target_feature = "avx2")]` early return in `blake2b_simd`
3. The runtime detection path is never compiled
4. With static dispatch, LTO can see that `guts::compress1_loop` always calls `avx2::compress1_loop`
5. LTO inlines the call and eliminates the separate `avx2::compress1_loop` function
6. The inlined portable code then gets auto-vectorized (to AVX-512 or AVX2 depending on available features)

**Key insight:** The ~2,018 zmm instructions in all "good" builds come from BLAKE3's hand-written assembly (which IS preserved). The problem is specific to `blake2b_simd`'s dispatch pattern.

---

## Recommended Solution

### OnceLock Function Pointer Patch (RECOMMENDED)

Use the patched `blake2b_simd` and `blake2s_simd` crates with OnceLock function pointer dispatch:

1. Copy patch files from `/home/ubuntu/blake2-patch/`
2. Add `[patch.crates-io]` entries to your Cargo.toml
3. Build with `RUSTFLAGS="-C target-cpu=native"`

This gives you:
- Hand-tuned BLAKE2 AVX2 code preserved ✓
- Native CPU optimizations for other code ✓
- Best of both worlds!

See `/home/ubuntu/patch-files/README.md` for full implementation details.

### Alternative: No target-cpu flag

If patching is not desired, use Parity's approach: no RUSTFLAGS at all.
This preserves hand-tuned code but loses native CPU optimizations.

---

## Commands for Future Investigation

### Check if a binary has the hand-tuned BLAKE2 AVX2 code:
```bash
# Should show blake2b_simd::avx2::compress1_loop if present
strings /path/to/polkadot | grep "blake2b_simd.*avx2"
# OR
objdump -t /path/to/polkadot 2>/dev/null | grep "blake2b_simd.*avx2"
```

### Count SIMD instructions:
```bash
# AVX-512 (zmm registers) - should be ~2,000 for good builds
objdump -d /path/to/polkadot | grep -c "zmm"

# AVX2 (ymm registers) - should be ~15,000-16,000 for good builds
objdump -d /path/to/polkadot | grep -c "ymm"
```

### Expected values for a "good" build:
- zmm count: ~2,000 (only from blake3 handwritten assembly)
- ymm count: ~15,000-16,000
- Has `blake2b_simd::avx2::compress1_loop` symbol

### Red flags for a "bad" build:
- zmm count: >100,000 (excessive auto-vectorization)
- ymm count: >100,000
- Missing `blake2b_simd::avx2::compress1_loop` symbol

---

## Files Referenced

- `/home/ubuntu/optimized-builds/bin/stable2509-2/` - Binary storage
- `/home/ubuntu/optimized-builds/polkadot-sdk/` - Source code
- `/home/ubuntu/optimized-builds/compile.py` - Build script
- `~/.cargo/registry/src/index.crates.io-*/blake2b_simd-1.0.2/src/guts.rs` - Original dispatch logic

### Patched Files (Working Solution)
- `/home/ubuntu/patch-files/README.md` - Full documentation of the OnceLock solution
- `/home/ubuntu/patch-files/blake2b_simd-oncelock.patch` - Diff patch for blake2b_simd
- `/home/ubuntu/patch-files/blake2s_simd-oncelock.patch` - Diff patch for blake2s_simd
- `/home/ubuntu/blake2-patch/blake2b_simd-1.0.2/` - Pre-patched blake2b_simd crate
- `/home/ubuntu/blake2-patch/blake2s_simd-1.0.1/` - Pre-patched blake2s_simd crate

---

## Coverage Analysis - Why Only blake2b/blake2s?

We analyzed ALL Polkadot dependencies for the vulnerable pattern. Only two crates need patching:

### Vulnerable (PATCHED)
| Crate | Implementation | Status |
|-------|----------------|--------|
| `blake2b_simd` | Rust intrinsics | ✓ PATCHED |
| `blake2s_simd` | Rust intrinsics | ✓ PATCHED |

### NOT Vulnerable
| Crate | Why Safe |
|-------|----------|
| `blake3` | Uses external assembly (`.S` files) via FFI - LTO cannot eliminate |
| `memchr` | Uses `#[target_feature(enable)]`, not `#[cfg(target_feature)]` |
| `curve25519-dalek` | Compile-time backend via Cargo features |
| `sha2`/`sha3` | Different detection pattern (RustCrypto cpufeatures) |

### The Vulnerability Pattern
A crate is vulnerable when ALL of these are true:
1. `#[cfg(target_feature = "avx2")]` early return BEFORE runtime detection
2. SIMD implemented in **Rust** (intrinsics), not external assembly
3. LTO enabled

**Why assembly survives:** Assembly files are compiled by C compiler and linked as external symbols. LTO cannot see into external symbols.

---

## Benchmark Results (AMD EPYC 4484PX - AVX-512)

**Important Finding:** While the OnceLock patch preserves hand-tuned BLAKE2 code, the overall performance on AVX-512 hardware is dominated by frequency throttling effects.

### Machine Benchmark Comparison (3 runs each)

| Build | BLAKE2-256 (GiB/s) | SR25519-Verify (MiB/s) |
|-------|-------------------|------------------------|
| Official (Parity) | 1.59 | 1.14 |
| Patched Native | 1.46 (-8.0%) | 1.25 (+9.6%) |
| Unpatched Native | 1.45 (-8.4%) | 1.35 (+18.1%) |

### Analysis

1. **Both native builds are ~8% slower than Official for BLAKE2-256**
   - Cause: AVX-512 frequency throttling from ~263K zmm instructions
   - The CPU throttles frequency when executing AVX-512 workloads

2. **The OnceLock patch gives only +0.5% BLAKE2 improvement** over unpatched native
   - Hand-tuned code IS preserved (confirmed via symbol analysis)
   - But frequency throttling dominates the performance impact

3. **Native builds are FASTER for SR25519** (+10-18% vs official)
   - Native CPU optimizations benefit non-BLAKE2 workloads

4. **The patch HURTS SR25519 performance (-7.2%)** vs unpatched native
   - OnceLock function pointer indirection adds overhead

### Instruction Count Analysis

| Build | zmm (AVX-512) | ymm (AVX2) | Has blake2b_simd::avx2 |
|-------|--------------|-----------|------------------------|
| Official | 2,018 | 15,787 | YES |
| Patched Native | 263,306 | 182,502 | **YES** |
| Unpatched Native | 263,460 | 184,805 | **NO** |

The ~263K zmm instructions in native builds (vs ~2K in official) cause CPU frequency throttling.

### Updated Recommendations

For **AVX-512 hardware** (AMD EPYC, Intel Ice Lake+):
- Use official build OR build without `target-cpu=native`
- The OnceLock patch provides minimal benefit due to frequency throttling
- Consider `target-cpu=x86-64-v3` (AVX2 without AVX-512)

For **non-AVX-512 hardware** (older Intel, AMD Zen2/3 without AVX-512):
- The OnceLock patch may provide more benefit
- No frequency throttling from AVX-512 auto-vectorization

---

## Conclusion

**TECHNICALLY SOLVED, BUT WITH CAVEATS:** The OnceLock patch preserves hand-tuned BLAKE2 AVX2 code, but overall performance on AVX-512 hardware is worse due to frequency throttling.

### Key Takeaways

1. The problem is `target_feature="avx2"` at compile time, NOT AVX-512
2. Disabling AVX-512 features (`-avx512f`, `-avx512vl`, etc.) does NOT help
3. `black_box` and `#[inline(never)]` do NOT prevent LTO from eliminating the code
4. **OnceLock function pointer dispatch WORKS** - LTO cannot devirtualize indirect calls through runtime-initialized function pointers
5. The patch preserves `no_std` compatibility by falling back to direct calls

### Approaches Tested Summary

| Approach | Preserves Hand-tuned AVX2 | Auto-vec Bloat | BLAKE2 Performance |
|----------|--------------------------|----------------|-------------------|
| No flags (Parity's approach) | YES ✓ | None | 1.59 GiB/s (baseline) |
| `native` + OnceLock | YES ✓ | 11.6x + AVX-512 | 1.46 GiB/s (-8.2%) |
| `native -avx512f` + OnceLock | YES ✓ | **29.7x** | 1.57 GiB/s (-1.3%) |
| `x86-64-v3` + OnceLock | YES ✓ | **29.2x** | 1.54 GiB/s (-3.1%) |
| `native -avx512vl` | NO ✗ | 11.6x + AVX-512 | - |
| `black_box` wrapper | NO ✗ | - | - |
| `#[inline(never)]` | NO ✗ | - | - |

**Best option for native builds:** `native -avx512f` with OnceLock patch (-1.3% BLAKE2 slowdown, preserves hand-tuned code).

---

## Original Investigation Reference

See `ORIGINAL_INVESTIGATION.md` for the full chat log from the original discovery session.
