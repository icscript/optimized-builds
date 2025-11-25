From Math Crypto Website



## Summary v0.9.27

Based on our detailed analysis, we have compiled polkadot version 0.9.27 by modifying the production profile in the Cargo.toml root folder of the polkadot source code.

In the table below, the benchmark scores (higher is better) and the timing of the Remark Extrinsic (lower is better) are listed for a few machines with different CPU architectures.

Based on their published statistics, these settings seemed to produce the best results:

Codegen-units 1

Lto fat (for our initial tests we should use thin for speed, once everythings working we could change to fat)

Opt-level 3

## How to compile
In order to generate an optimal build, you need to modify the Cargo.toml file as follows:

[profile.production]
inherits = "release"
codegen-units = CHANGE THIS
lto = CHANGE THIS
opt-level = CHANGE THIS
where CHANGE THIS determines the build profile specified above. Afterwards, you build as usual:

rustup override set nightly
export RUSTFLAGS="-C target-cpu=native"
cargo build --profile=production --target=x86_64-unknown-linux-gnu --locked -Z unstable-options
Instead of manually building, you can also use our convenient Python script. It allows you to build several binaries in one go and specify options in a simpler way (I would like to use the python script(updating it as required).

# Optimization options
!! Page WIP !!

## How to specify options
Build options can be specified as the environment variable

export RUSTFLAGS="-C option1=value1 -C option2=value2"
before running cargo build.

Another possibility is to collect all options in a custom profile that is specified in the Cargo.toml file at the root of the polkadot directory. In the polkadot source, there are already two such profiles:

[profile.release]
# Polkadot runtime requires unwinding.
panic = "unwind"
opt-level = 3

[profile.production]
inherits = "release"
lto = true
codegen-units = 1

As explained below, the production profile includes more advanced optimization options.

## Codegen
The maximum number of code generation units a crate can be split into. Standard value is 16. Choosing 1 may improve the performance of generated code.

In our testing, codegen=True means -C codegen=1, whereas codegen=False does not specify it explicitly and thus takes the default value.

## LTO
Let LLVM optimize the whole code during linking. Three modes can be set with -C lto=?:

no: self-explanatory
fat: optimizations across whole code; longest build time
thin: compromise between fat and disabled; significantly faster build time
If the option -C lto is not provided or not specified with the options above, LTO can still be enabled. To avoid ambiguities, we always specify the LTO options in our optimized builds.

NOTE: LTO (thin or fat) does not always lead to improvement. Furthermore, while fat lto is much slower to compile, it is not always better than thin LTO. See here for details.
IMPORTANT: Specifying lto in RUSTFLAGS does not work and gives error: lto can only be run for executables, cdylibs and static library outputs. Hence, it need to be specified in Cargo.toml

## Architecture
TODO

Find your CPU architecture with rustc --print target-cpus Taking target-cpu = native will automatically take the most specific (advanced) architecture.

## Opt-level
TODO



# Compile Instructions

(Section has pre-req's that may be needed, not sure if Python script installs them or calls them out)

## Install libraries
One time only: install required libraries and rust

sudo apt install cmake clang lld build-essential git libclang-dev pkg-config libssl-dev
curl https://sh.rustup.rs -sSf | sh
source $HOME/.cargo/env

## Get new release and compile
With each new polkadot release: Update rust

rustup update
Get the source files of the official polkadot release version VER. Beware: The commands below remove the old files!

export VER=0.9.26
mkdir -p ~/optimized_polkadot
cd ~/optimized_polkadot
rm -rf polkadot
git clone --depth 1 --branch v${VER} https://github.com/paritytech/polkadot.git

cd polkadot
./scripts/init.sh
cargo fetch
Choose your optimization options. The options below work well on our test machine (i7-12700). See here for more details and which options you can choose

rustup override set nightly
export RUSTFLAGS="-C target-cpu=native -C codegen=1"
cargo build --release --target=x86_64-unknown-linux-gnu --locked -Z unstable-options
Compiling takes a little while. On a fast machine with NVMe storage, it is about 15 minutes.

Important:
From our latest analysis, we have detected better build options that have to be specified as a profile in the Cargo.toml file. Please use our convenient Python script for building.

## Benchmark and deploy
Benchmark your optimized binary polkadot_opt to make sure it runs OK.

cp target/x86_64-unknown-linux-gnu/release/polkadot ~/optimized_polkadot/polkadot_opt
cd ~/optimized_polkadot
polkadot_opt benchmark machine --disk-duration 30
Optional: compare with the official binary to see if it was worth the trouble.

cd ~/optimized_polkadot/
wget https://github.com/paritytech/polkadot/releases/download/v${VER}/polkadot
chmod +x polkadot
polkadot benchmark machine --disk-duration 30
If you are happy, deploy the optimized binary. With systemd, you can simply replace the official binary with the optimized one and restart the service. For docker, you will need to build your own docker image.

## Problems
New polkadot versions can require newer version of system libraries and programs (for example, cmake). Updating your machine with sudo apt update is advisable.
