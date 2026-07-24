# Third-Party Notices

## Apple Virtualization sample

Portions of the Swift virtual-machine runner were adapted from Apple’s
“Running macOS in a virtual machine on Apple silicon” sample.

- Official documentation: <https://developer.apple.com/documentation/virtualization/running-macos-in-a-virtual-machine-on-apple-silicon>
- Reviewed archive: <https://docs-assets.developer.apple.com/published/c8bf24264607/RunningMacOSInAVirtualMachineOnAppleSilicon.zip>
- Archive SHA-512: `c8bf24264607633b6dbdf242cf610f9a753d2e9356d9899201be671485987083e9c6ba0371b93aea1bfc0cadcd652b06d82a4114acce04fef595e5b9bece1dd2`
- Reviewed: 2026-07-23
- License: [Apple-Sample-Code-MIT.txt](LICENSES/Apple-Sample-Code-MIT.txt)

Adapted areas:

- `runner/Sources/VMRunner/AppDelegate.swift`
- `runner/Sources/VMRunner/VMConfigurationBuilder.swift`
- `runner/Sources/VMRunner/VMDelegate.swift`
- `runner/Sources/VMRunner/VMPaths.swift`
- `runner/Sources/VMInstaller/main.swift`
- `runner/VMRunner.entitlements`
- `runner/VMInstaller.entitlements`

The project is independently maintained and is not affiliated with, endorsed
by, or sponsored by Apple Inc. Apple, macOS, and Xcode are trademarks of Apple
Inc.
