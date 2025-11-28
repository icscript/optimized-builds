# Profile-Guided Optimization (PGO) and BOLT for Polkadot

This document describes how to apply PGO and BOLT optimizations to Polkadot binaries for improved validator performance. These optimizations complement the existing LTO, codegen-units, and target-cpu optimizations in `compile.py`.

## Overview

| Optimization | Type | Expected Gain | Stacks With |
|--------------|------|---------------|-------------|
| LTO (fat) | Compile-time | Baseline | - |
| PGO | Compile-time | 10-20% | LTO |
| BOLT | Post-link | 5-15% | LTO + PGO |

**Total potential improvement: 15-35% over LTO alone.**

## How PGO Works

PGO is a two-pass compilation approach:

1. **Instrumented build**: Compile with profiling instrumentation
2. **Profile collection**: Run the instrumented binary under representative workload
3. **Optimized build**: Recompile using collected profile data

The compiler uses the profile data to:
- Optimize hot code paths
- Improve branch prediction hints
- Better inline decisions
- Optimize memory layout for cache efficiency

## How BOLT Works

BOLT (Binary Optimization and Layout Tool) is a post-link optimizer that:
- Reorders functions based on call frequency
- Reorders basic blocks within functions
- Splits hot/cold code paths
- Improves instruction cache locality

BOLT works on the final binary, so it stacks with PGO and LTO.

---

## Profiling Methodology

### Recommended Approach: Active Kusama/Polkadot Node

The most representative profile data comes from running on the live network:

| Workload Type | Validation Paths | Networking | Active Set Paths |
|---------------|------------------|------------|------------------|
| Benchmarks only | Partial | No | No |
| Block replay | Yes | No | No |
| Inactive node (mainnet) | Yes | Yes | No |
| Active validator (mainnet) | Yes | Yes | Yes |

**For validator optimization, active-set profiling captures the critical paths:**
- PVF (Parachain Validation Function) execution
- Backing statement timing
- Approval voting
- Availability distribution

### Profile Collection Options

**Option A: Active Kusama Validator (Best)**
- Run instrumented binary on your Kusama validator
- Collect profiles during 1-2 eras (~6-12 hours)
- Captures real active-set workload with 1000+ peer connections
- Instrumentation overhead: 10-30% (shouldn't cause slashing)

**Option B: Inactive Node + Replay (Lower Risk)**
- Run instrumented binary as non-validating node
- Supplement with block replay for validation path coverage
- Misses active-set specific paths (PVF, backing)

**Option C: Zombienet (Controlled Environment)**
- Local test network with simulated parachains
- Exercises active-set code paths without mainnet risk
- Lower peer count, but same code paths

### Choosing a Profiling Approach

| Approach | Active-Set Paths | Real Networking | Effort | Best For |
|----------|------------------|-----------------|--------|----------|
| Inactive Kusama only | No | Yes (1000+ peers) | Low | p2p patterns only |
| Zombienet only | Yes | Limited (5-20 nodes) | Medium | Active-set code paths |
| Zombienet + Inactive Kusama | Yes | Yes | Higher | Most complete coverage |

**Key insight:** For validator performance (backing points, missed votes), the critical hot paths are PVF execution, backing statements, and approval voting. These **only run in active set** - an inactive node never touches them.

**Recommendations:**

| If you want... | Do this |
|----------------|---------|
| Simplest approach that covers active-set paths | Zombienet only |
| Most complete coverage | Zombienet + Inactive Kusama |
| Lowest effort (but misses key paths) | Inactive Kusama only |

**Note on replay:** If you're already running a Kusama node (active or inactive), replay is redundant - the node is already importing/validating blocks in real-time. Skip replay unless you need offline profiling without a running node.

---

## Zombienet for PGO Profiling

Zombienet creates a local test network that exercises active-set validator code paths. For full documentation, see the [Zombienet README](https://github.com/paritytech/zombienet).

### Why Zombienet for PGO

PGO optimizes based on **which code paths are executed** (branch frequency), not the number of peers or exact timing. The code paths for PVF validation, backing, and approval voting are identical whether you have 5 Zombienet peers or 1000 Kusama peers.

Zombienet advantages:
- You control which node is in active set
- Parachains produce blocks → your node does real PVF validation
- No mainnet risk, no token requirements
- Reproducible environment

### Installation

Zombienet supports multiple providers. For profiling, **native** is simplest (runs binaries as local processes).

```bash
# Option 1: Download binary directly
wget https://github.com/paritytech/zombienet/releases/latest/download/zombienet-linux-x64
chmod +x zombienet-linux-x64
sudo mv zombienet-linux-x64 /usr/local/bin/zombienet

# Option 2: Via npm
npm install -g @parity/zombienet
```

### Parachain Validation Load

**Important:** Just having validators doesn't create PVF load. You need **parachains with collators actively producing blocks**.

Polkadot SDK includes test collators for this purpose:
- `adder-collator` - Simple test parachain
- `undying-collator` - Another test parachain

These are built alongside polkadot when you compile with `-p polkadot-parachain` or `-p test-parachain`.

### Sample Configuration for Profiling

Create `zombienet-pgo.toml`:

```toml
[settings]
timeout = 1000

[relaychain]
chain = "rococo-local"
# Point to your instrumented polkadot binary
default_command = "/path/to/instrumented/polkadot"

  # Validator nodes - one will be your profiling target
  [[relaychain.nodes]]
  name = "alice"
  validator = true

  [[relaychain.nodes]]
  name = "bob"
  validator = true

  [[relaychain.nodes]]
  name = "charlie"
  validator = true

  [[relaychain.nodes]]
  name = "dave"
  validator = true

# Parachain 1 - creates PVF validation load
[[parachains]]
id = 1000
cumulus_based = true

  # Collator produces blocks for validators to validate
  [[parachains.collators]]
  name = "collator-1000"
  command = "/path/to/polkadot-parachain"
  args = ["--", "--chain", "rococo-local"]

# Parachain 2 - more load (optional)
[[parachains]]
id = 2000
cumulus_based = true

  [[parachains.collators]]
  name = "collator-2000"
  command = "/path/to/polkadot-parachain"
  args = ["--", "--chain", "rococo-local"]
```

### Running Zombienet for Profile Collection

```bash
# Set profile output directory
export PGO_PROFILE_DIR="/tmp/pgo-profiles"
mkdir -p $PGO_PROFILE_DIR

# Build instrumented binaries first (see PGO Implementation section)
# Then update zombienet-pgo.toml to point to instrumented binaries

# Launch the network
zombienet spawn zombienet-pgo.toml

# Let it run for 1-2 hours
# Parachains will produce blocks, validators will execute PVF validation
# Profile data accumulates in PGO_PROFILE_DIR

# Stop with Ctrl+C
# Collect profiles from PGO_PROFILE_DIR
```

### What Gets Profiled

With this setup, your instrumented validators will exercise:
- **PVF compilation** (polkadot-prepare-worker)
- **PVF execution** (polkadot-execute-worker)
- **Backing** - validating parachain candidates
- **Availability distribution** - erasure coding chunks
- **Approval voting** - checking backed candidates
- **GRANDPA** - finality voting
- **Block import** - relay chain blocks

This covers the critical validator hot paths that an inactive mainnet node would miss.

### Combining with Inactive Kusama (Optional)

For most complete coverage, collect profiles from both:

1. **Zombienet** (1-2 hours) - active-set paths
2. **Inactive Kusama node** (several hours) - real networking patterns

Then merge:

```bash
llvm-profdata merge \
  -output=/path/to/combined.profdata \
  /tmp/pgo-profiles/*.profraw \
  /var/lib/polkadot/kusama-profiles/*.profraw
```

### Zombienet vs Other Providers

| Provider | Setup Complexity | Resource Usage | Use Case |
|----------|------------------|----------------|----------|
| Native | Low | Moderate (all on one machine) | Development, PGO profiling |
| Podman | Medium | Moderate | Isolated containers |
| Kubernetes | High | Scalable | CI/CD, large scale testing |

For PGO profiling, **native** is recommended - simplest setup and you're profiling the actual binary behavior, not container overhead.

---

## PGO Implementation

### Prerequisites

```bash
# Ensure LLVM tools are available
which llvm-profdata  # Required for merging profiles

# On Arch Linux
sudo pacman -S llvm

# On Ubuntu/Debian
sudo apt install llvm
```

### Step 1: Build Instrumented Binary

Modify the compile process to add profile generation:

```python
# In compile.py, add to RUSTFLAGS for instrumented build:
RUSTFLAGS = "-C target-cpu=native -C profile-generate=/var/lib/polkadot/pgo-profiles"
```

Or manually:

```bash
cd ~/polkadot-optimized/polkadot-sdk

# Set profile output directory
export PGO_PROFILE_DIR="/var/lib/polkadot/pgo-profiles"
mkdir -p $PGO_PROFILE_DIR

# Build with instrumentation
RUSTFLAGS="-C target-cpu=native -C profile-generate=$PGO_PROFILE_DIR" \
  cargo build -p polkadot --profile=production --locked --target=x86_64-unknown-linux-gnu
```

**Note:** All three binaries (polkadot, polkadot-prepare-worker, polkadot-execute-worker) will be instrumented.

### Step 2: Collect Profiles

Deploy instrumented binaries and run under representative load:

```bash
# Copy instrumented binaries to node
# Ensure all 3 binaries are from the same instrumented build
cp target/x86_64-unknown-linux-gnu/production/polkadot /usr/local/bin/
cp target/x86_64-unknown-linux-gnu/production/polkadot-prepare-worker /usr/local/bin/
cp target/x86_64-unknown-linux-gnu/production/polkadot-execute-worker /usr/local/bin/

# Run node normally - profiles accumulate in PGO_PROFILE_DIR
systemctl start polkadot

# Let it run for several hours (1-2 eras recommended for validators)
# Profile files (.profraw) accumulate in the profile directory

# Stop and collect profiles
systemctl stop polkadot
ls /var/lib/polkadot/pgo-profiles/
# You'll see files like: default_12345_0.profraw
```

### Step 3: Merge Profiles

```bash
# Merge all .profraw files into a single .profdata file
llvm-profdata merge \
  -output=/path/to/merged.profdata \
  /var/lib/polkadot/pgo-profiles/*.profraw

# Verify the merged profile
llvm-profdata show /path/to/merged.profdata
```

### Step 4: Build Optimized Binary

```bash
cd ~/polkadot-optimized/polkadot-sdk

# Build with profile data
RUSTFLAGS="-C target-cpu=native -C profile-use=/path/to/merged.profdata" \
  cargo build -p polkadot --profile=production --locked --target=x86_64-unknown-linux-gnu
```

---

## BOLT Implementation

BOLT provides additional optimization after PGO+LTO compilation.

### Prerequisites

```bash
# Install BOLT (part of LLVM project)
# On Arch Linux
sudo pacman -S llvm

# On Ubuntu 22.04+
sudo apt install llvm

# Verify BOLT is available
which llvm-bolt perf2bolt
```

### Step 1: Collect Runtime Profile with perf

Run the PGO-optimized binary and collect perf data:

```bash
# Start node
systemctl start polkadot

# Collect perf data (run for 1-2 hours for good coverage)
sudo perf record -e cycles:u -j any,u -a -o perf.data -- sleep 3600

# Stop collection
systemctl stop polkadot
```

### Step 2: Convert perf Data for BOLT

```bash
# Convert perf data to BOLT format
perf2bolt \
  -p perf.data \
  -o perf.fdata \
  /usr/local/bin/polkadot

# This may take several minutes for large binaries
```

### Step 3: Apply BOLT Optimization

```bash
# Apply BOLT optimizations
llvm-bolt /usr/local/bin/polkadot \
  -o /usr/local/bin/polkadot.bolt \
  -data=perf.fdata \
  -reorder-blocks=ext-tsp \
  -reorder-functions=hfsort \
  -split-functions \
  -split-all-cold \
  -dyno-stats

# Repeat for worker binaries if desired
llvm-bolt /usr/local/bin/polkadot-prepare-worker \
  -o /usr/local/bin/polkadot-prepare-worker.bolt \
  -data=perf.fdata \
  -reorder-blocks=ext-tsp \
  -reorder-functions=hfsort \
  -split-functions \
  -split-all-cold

llvm-bolt /usr/local/bin/polkadot-execute-worker \
  -o /usr/local/bin/polkadot-execute-worker.bolt \
  -data=perf.fdata \
  -reorder-blocks=ext-tsp \
  -reorder-functions=hfsort \
  -split-functions \
  -split-all-cold

# Replace original binaries
mv /usr/local/bin/polkadot.bolt /usr/local/bin/polkadot
mv /usr/local/bin/polkadot-prepare-worker.bolt /usr/local/bin/polkadot-prepare-worker
mv /usr/local/bin/polkadot-execute-worker.bolt /usr/local/bin/polkadot-execute-worker
```

---

## Integration with compile.py

### Recommended Workflow

1. **Run existing compile.py** to build the 5 baseline configurations
2. **Benchmark** using `run_benchmarks.py` to identify best baseline
3. **Apply PGO** to the winning configuration only
4. **Benchmark again** to measure PGO improvement
5. **(Optional) Apply BOLT** for additional gains

### Why Profile One Configuration

PGO profiles are somewhat build-config-specific:
- Different LTO modes produce different code layouts
- Branch frequencies may differ between opt-level 2 vs 3
- Profiling all 5 configurations would require 5x the profiling time

**Recommendation:** Benchmark first, then apply PGO to the winner.

### Future: Adding PGO to compile.py

A future enhancement could add PGO as a compile option:

```python
# Potential addition to compile.py opts
opts.append({
    'toolchain': 'stable',
    'arch': 'native',
    'codegen-units': 1,
    'lto': 'fat',
    'opt-level': 3,
    'pgo': '/path/to/merged.profdata'  # New option
})
```

This would require modifying the `compile()` function to:
1. Check for `pgo` key in opts
2. Add `-C profile-use={path}` to RUSTFLAGS when present
3. Skip instrumented builds (separate workflow)

---

## Complete PGO+BOLT Workflow Example

```bash
#!/bin/bash
# Full PGO + BOLT optimization workflow

VERSION="stable2509-2"
WORK_DIR=~/polkadot-optimized
PROFILE_DIR=/var/lib/polkadot/pgo-profiles
MERGED_PROFILE=/tmp/polkadot-pgo.profdata

# --- Phase 1: Instrumented Build ---
echo "Building instrumented binary..."
cd $WORK_DIR/polkadot-sdk

RUSTFLAGS="-C target-cpu=native -C profile-generate=$PROFILE_DIR" \
  cargo build -p polkadot --profile=production --locked \
  --target=x86_64-unknown-linux-gnu

# Deploy instrumented binaries to node and run for 6-12 hours
# (manual step - depends on your deployment)

# --- Phase 2: Merge Profiles ---
echo "Merging profiles..."
llvm-profdata merge -output=$MERGED_PROFILE $PROFILE_DIR/*.profraw

# --- Phase 3: PGO Build ---
echo "Building with PGO..."
# Clean previous build
cargo clean -p polkadot

RUSTFLAGS="-C target-cpu=native -C profile-use=$MERGED_PROFILE" \
  cargo build -p polkadot --profile=production --locked \
  --target=x86_64-unknown-linux-gnu

# --- Phase 4: BOLT (Optional) ---
# Deploy PGO binary, collect perf data, apply BOLT
# See BOLT section above for commands

echo "PGO build complete!"
echo "Binary: $WORK_DIR/polkadot-sdk/target/x86_64-unknown-linux-gnu/production/polkadot"
```

---

## Troubleshooting

### Profile files not generated

- Ensure the binary runs long enough (profiles written on exit)
- Check directory permissions for profile output path
- Verify RUSTFLAGS were applied during compilation

### llvm-profdata merge fails

- Ensure all .profraw files are from the same instrumented build
- Check for corrupted profiles (node crashed during profiling)
- Try merging with `--failure-mode=any` to skip bad profiles

### BOLT fails with "insufficient profile data"

- Collect perf data for longer duration
- Ensure perf is capturing the correct process
- Try with fewer BOLT options (remove `-split-all-cold`)

### Performance regression after PGO

- Profile workload may not match production workload
- Try collecting profiles from active validator sessions
- Verify profile merge succeeded without errors

---

## Performance Expectations

Based on community experience with PGO+BOLT on similar Rust projects:

| Metric | Expected Improvement |
|--------|---------------------|
| Block import time | 10-20% faster |
| PVF execution | 10-25% faster |
| Memory usage | Slight reduction |
| Binary size | May increase slightly with BOLT |

**Note:** Actual results depend on workload characteristics and hardware.

---

## References

- [Rust PGO Documentation](https://doc.rust-lang.org/rustc/profile-guided-optimization.html)
- [LLVM BOLT](https://github.com/llvm/llvm-project/tree/main/bolt)
- [Chromium PGO Guide](https://chromium.googlesource.com/chromium/src/+/main/docs/pgo.md) (methodology reference)
