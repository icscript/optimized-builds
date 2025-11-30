# Blake2 SIMD Patch for LTO + target-cpu=native Compatibility

## Problem

When building with `target-cpu=native` on AVX2+ hardware (like Zen4), the
`blake2b_simd` and `blake2s_simd` crates use compile-time feature detection
that causes LTO to eliminate hand-tuned AVX2 implementations, replacing them
with autovectorized portable code.

## Root Cause

In `guts.rs`, the `avx2_if_supported()` and `sse41_if_supported()` functions
check `#[cfg(target_feature = "avx2")]` BEFORE runtime detection. When
`target-cpu=native` is used, this compile-time check succeeds, making the
dispatch deterministic. LTO then inlines and optimizes away the separate
hand-tuned implementations.

## Investigation Summary

Initial hypothesis was that AVX-512 autovectorization was replacing hand-tuned AVX2 code.
Testing proved this wrong - the root cause is compile-time feature detection, not AVX-512.

### Approaches Tested

| Approach | Preserves Hand-tuned AVX2 | Notes |
|----------|--------------------------|-------|
| No flags (Parity's approach) | YES ✓ | Official release method, no native optimizations |
| `native -avx512vl` | NO ✗ | Disabling AVX-512VL doesn't help |
| `native -avx512f` | NO ✗ | Disabling AVX-512F shifts to AVX2 autovectorization but still eliminates hand-tuned |
| Runtime detection first | NO ✗ | LTO still sees through runtime detection |
| `#[inline(never)]` | NO ✗ | LTO ignores this attribute |
| `std::hint::black_box` | NO ✗ | LTO still optimizes through black_box |
| **OnceLock function pointer** | **YES ✓** | **WORKING SOLUTION** |

**Key finding:** The issue is that `target-cpu=native` sets `target_feature="avx2"` at compile time.
Even with runtime detection first, LTO knows the result will always be `true` and can inline/optimize.

## The Working Solution: OnceLock Function Pointer Dispatch

LTO cannot devirtualize a function pointer stored in `OnceLock` that's initialized at runtime.
By dispatching through an indirect function call, the compiler cannot inline the target function.

### How It Works

```rust
use std::sync::OnceLock;

// Function pointer type
type Compress1LoopFn = unsafe fn(&[u8], &mut [Word; 8], Count, LastNode, Finalize, Stride);

// Static function pointer initialized at runtime
static COMPRESS1_AVX2: OnceLock<Compress1LoopFn> = OnceLock::new();

fn init_avx2_dispatch() {
    if is_x86_feature_detected!("avx2") {
        let _ = COMPRESS1_AVX2.set(avx2::compress1_loop);
    }
}

// In compress1_loop(), dispatch via function pointer:
Platform::AVX2 => {
    if let Some(func) = COMPRESS1_AVX2.get() {
        unsafe { func(input, words, count, last_node, finalize, stride) };
        return;
    }
}
```

### Results

| Symbol | Unpatched (native) | OnceLock Patch (native) | Official (no flags) |
|--------|-------------------|------------------------|---------------------|
| blake2b_simd::avx2::compress1_loop | NO | **YES** ✓ | YES |
| blake2b_simd::avx2::compress4_loop | NO | **YES** ✓ | YES |
| blake3_hash_many_avx2 | YES | YES | YES |

## Setup Instructions

### 1. Create patch directory and copy original crates

```bash
mkdir -p ~/blake2-patch/blake2b_simd-1.0.2
mkdir -p ~/blake2-patch/blake2s_simd-1.0.1

# Copy original crates from cargo cache
cp -r ~/.cargo/registry/src/index.crates.io-*/blake2b_simd-1.0.2/* \
      ~/blake2-patch/blake2b_simd-1.0.2/

cp -r ~/.cargo/registry/src/index.crates.io-*/blake2s_simd-1.0.1/* \
      ~/blake2-patch/blake2s_simd-1.0.1/
```

### 2. Apply the OnceLock function pointer patch

For `blake2b_simd-1.0.2/src/guts.rs`:

**Add import at top:**
```rust
#[cfg(feature = "std")]
use std::sync::OnceLock;
```

**Add after MAX_DEGREE constant:**
```rust
// Function pointer types for indirect dispatch to prevent LTO inlining
#[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
type Compress1LoopFn = unsafe fn(&[u8], &mut [Word; 8], Count, LastNode, Finalize, Stride);

#[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
type Compress4LoopFn = unsafe fn(&mut [Job; 4], Finalize, Stride);

// Static function pointers initialized at runtime - LTO cannot see through these
#[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
static COMPRESS1_AVX2: OnceLock<Compress1LoopFn> = OnceLock::new();

#[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
static COMPRESS4_AVX2: OnceLock<Compress4LoopFn> = OnceLock::new();

#[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
fn init_avx2_dispatch() {
    if is_x86_feature_detected!("avx2") {
        let _ = COMPRESS1_AVX2.set(avx2::compress1_loop);
        let _ = COMPRESS4_AVX2.set(avx2::compress4_loop);
    }
}
```

**Modify detect() to call init:**
```rust
pub fn detect() -> Self {
    // Initialize function pointer dispatch before detection
    #[cfg(all(feature = "std", any(target_arch = "x86", target_arch = "x86_64")))]
    {
        init_avx2_dispatch();
    }
    // ... rest of detect() unchanged
}
```

**Modify compress1_loop() AVX2 arm:**
```rust
Platform::AVX2 => {
    #[cfg(feature = "std")]
    {
        if let Some(func) = COMPRESS1_AVX2.get() {
            unsafe { func(input, words, count, last_node, finalize, stride) };
            return;
        }
    }
    #[cfg(not(feature = "std"))]
    unsafe {
        avx2::compress1_loop(input, words, count, last_node, finalize, stride);
    }
},
```

**Modify compress4_loop() similarly:**
```rust
Platform::AVX2 => {
    #[cfg(feature = "std")]
    {
        if let Some(func) = COMPRESS4_AVX2.get() {
            unsafe { func(jobs, finalize, stride) };
            return;
        }
    }
    #[cfg(not(feature = "std"))]
    unsafe {
        avx2::compress4_loop(jobs, finalize, stride);
    }
},
```

For `blake2s_simd-1.0.1/src/guts.rs`, apply similar changes for `compress8_loop`.

### 3. Add patch to your project's Cargo.toml

```toml
[patch.crates-io]
blake2b_simd = { path = "/home/ubuntu/blake2-patch/blake2b_simd-1.0.2" }
blake2s_simd = { path = "/home/ubuntu/blake2-patch/blake2s_simd-1.0.1" }
```

### 4. Build with native optimizations

```bash
RUSTFLAGS="-C target-cpu=native" cargo build --release
```

## Verification

After building, verify the hand-tuned code survived. Replace `BINARY` with your binary path.

### BLAKE2b (blake2b_simd)

```bash
# Check for avx2::compress1_loop symbol (should exist)
nm -C BINARY | grep "blake2b_simd.*avx2::compress1_loop"

# Check for avx2::compress4_loop symbol (should exist)
nm -C BINARY | grep "blake2b_simd.*avx2::compress4_loop"
```

### BLAKE3

```bash
# Check for blake3_hash_many_avx2 symbol (should exist)
nm -C BINARY | grep "blake3_hash_many_avx2"
```

### Quick One-Liner Check

```bash
BINARY=target/production/polkadot && \
echo "=== BLAKE2b ===" && \
nm -C $BINARY | grep -E "blake2b_simd.*(avx2::compress1_loop|avx2::compress4_loop)" | head -2 && \
echo "=== BLAKE3 ===" && \
nm -C $BINARY | grep "blake3_hash_many_avx2" | head -1 && \
echo "=== SIMD counts ===" && \
echo "ymm: $(objdump -d $BINARY | grep -c ymm)" && \
echo "zmm: $(objdump -d $BINARY | grep -c zmm)"
```

## Expected Results

| Symbol | Unpatched (native) | OnceLock Patch | Official (no flags) |
|--------|-------------------|----------------|---------------------|
| blake2b_simd::avx2::compress1_loop | NO | YES ✓ | YES |
| blake2b_simd::avx2::compress4_loop | NO | YES ✓ | YES |
| blake3_hash_many_avx2 | YES | YES | YES |

**Note on SIMD counts:** The ymm/zmm instruction counts will still be high (~180k/~260k)
because only the BLAKE2 functions are patched. The rest of the codebase still benefits
from native CPU auto-vectorization with AVX-512. This is expected behavior - we're
preserving specific hand-tuned functions, not reducing overall AVX-512 usage.

## Failed Approaches (For Reference)

### 1. Runtime detection order swap
Moving `#[cfg(feature = "std")]` before `#[cfg(target_feature = "avx2")]` doesn't help
because LTO still knows the runtime check will return true.

### 2. `#[inline(never)]` attribute
LTO ignores `#[inline(never)]` during cross-crate optimization.

### 3. `std::hint::black_box`
```rust
if black_box(is_x86_feature_detected!("avx2")) { ... }
```
This doesn't prevent LTO from inlining the function being called inside the branch.

### 4. Disabling AVX-512 features
`-avx512f` or `-avx512vl` shifts auto-vectorization but doesn't preserve hand-tuned code
because the root cause is compile-time `target_feature` detection, not AVX-512.

## Notes

- This patch preserves `no_std` compatibility by falling back to direct calls when `std` is unavailable
- The OnceLock function pointer adds negligible overhead (one indirect call + atomic load)
- This is arguably a bug in the upstream crate's design when used with LTO; consider submitting a PR
- Parity's official releases use no RUSTFLAGS to avoid this issue entirely

## Parity's Official Build Configuration

Parity builds official Polkadot releases with:
```bash
cargo build --profile production
```

**No RUSTFLAGS at all** - this means:
- No `-C target-cpu=native`
- `target_feature="avx2"` is NOT set at compile time
- Runtime detection works as intended
- Hand-tuned SIMD implementations are preserved

The trade-off: no native CPU optimizations for other parts of the codebase.

## Coverage Analysis - Why Only blake2b/blake2s?

We analyzed all Polkadot dependencies for the vulnerable pattern (compile-time `cfg(target_feature)` before runtime detection). Here's why only `blake2b_simd` and `blake2s_simd` need patching:

### Vulnerable Crates (PATCHED)
| Crate | Pattern | Implementation | Status |
|-------|---------|----------------|--------|
| `blake2b_simd` | `#[cfg(target_feature)]` before runtime | Rust intrinsics | ✓ PATCHED |
| `blake2s_simd` | `#[cfg(target_feature)]` before runtime | Rust intrinsics | ✓ PATCHED |

### NOT Vulnerable Crates
| Crate | Why NOT Vulnerable |
|-------|-------------------|
| `blake3` | Uses **hand-written assembly** (`.S` files) via FFI - LTO cannot eliminate external symbols |
| `memchr` | Uses `#[target_feature(enable)]` for functions, not `#[cfg(target_feature)]` for dispatch |
| `curve25519-dalek` | Compile-time backend selection via Cargo features, no runtime dispatch |
| `sha2`/`sha3` | Uses RustCrypto `cpufeatures` crate with different detection pattern |
| `portable-atomic` | Detection only, no hand-tuned SIMD implementations |

### The Key Vulnerability Pattern

A crate is vulnerable when ALL of these are true:
1. Uses `#[cfg(target_feature = "avx2")]` for compile-time early return
2. Has runtime detection (`is_x86_feature_detected!`) as fallback
3. Implements SIMD code in **Rust** (intrinsics), not external assembly
4. Compile-time check comes BEFORE runtime check

**Why assembly survives but intrinsics don't:**
- Assembly files (`.S`) are compiled by a C compiler and linked as external symbols
- LTO cannot see into external symbols, so it can't inline/eliminate them
- Rust intrinsics are visible to LTO, which can inline and then eliminate "dead" functions

## Patch Files

Two types of patches are available:

### 1. Diff patches (for applying to cargo cache)
```bash
# Apply to cargo registry cache
cd ~/.cargo/registry/src/index.crates.io-*/
patch -p0 < /path/to/blake2b_simd-oncelock.patch
patch -p0 < /path/to/blake2s_simd-oncelock.patch
```

### 2. Pre-patched crate directories (for Cargo.toml patch)
```toml
[patch.crates-io]
blake2b_simd = { path = "/home/ubuntu/blake2-patch/blake2b_simd-1.0.2" }
blake2s_simd = { path = "/home/ubuntu/blake2-patch/blake2s_simd-1.0.1" }
```

## Applying to Future Versions

The patch should work on future versions as long as:
1. The crate uses `OnceLock` (available since Rust 1.70)
2. The function signatures remain compatible
3. The dispatch pattern in `compress*_loop()` remains similar

If function signatures change, update the type aliases accordingly.
