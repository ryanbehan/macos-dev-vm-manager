// Portions adapted from Apple sample code. See THIRD_PARTY_NOTICES.md.

import Foundation
import Virtualization
import VMInstallerCore
import VMRunnerCore
import Darwin

private enum InstallerError: Error, CustomStringConvertible {
    case usage(String)
    case unsupportedRestoreImage
    case destinationExists(String)
    case invalidDiskSize

    var description: String {
        switch self {
        case .usage(let message): return message
        case .unsupportedRestoreImage: return "The restore image has no configuration supported by this host."
        case .destinationExists(let path): return "The VM bundle destination already exists: \(path)"
        case .invalidDiskSize: return "Disk size must be at least 64 GiB."
        }
    }
}

@main
struct VMInstallerMain {
    static func main() async {
        do {
            try await run(Array(CommandLine.arguments.dropFirst()))
        } catch is CancellationError {
            if let record = try? InstallerRecordEncoder.encode(
                InstallerProgressRecord(event: "cancelled")
            ) {
                FileHandle.standardError.write(Data((record + "\n").utf8))
            }
            exit(130)
        } catch {
            if let record = try? InstallerRecordEncoder.encode(
                InstallerProgressRecord(
                    event: "failed",
                    message: String(describing: error)
                )
            ) {
                FileHandle.standardError.write(Data((record + "\n").utf8))
            }
            exit(EXIT_FAILURE)
        }
    }

    private static func run(_ arguments: [String]) async throws {
        if arguments == ["--version"] {
            print("0.1.0 protocol=1")
            return
        }
        guard let command = arguments.first else {
            throw InstallerError.usage(
                "Usage: VMInstaller inspect --restore latest|PATH | install --restore PATH --bundle PATH [--disk-size-gib N]"
            )
        }
        switch command {
        case "inspect":
            let source = try option("--restore", in: Array(arguments.dropFirst()))
            let image = try await restoreImage(source)
            print(try InstallerRecordEncoder.encode(try restoreRecord(image)))
        case "install":
            let remaining = Array(arguments.dropFirst())
            let source = try option("--restore", in: remaining)
            guard source != "latest" else {
                throw InstallerError.usage(
                    "Install requires a downloaded local IPSW path; inspect latest first."
                )
            }
            let bundle = URL(
                fileURLWithPath: try option("--bundle", in: remaining),
                isDirectory: true
            ).standardizedFileURL
            let sizeText = optionalOption("--disk-size-gib", in: remaining) ?? "128"
            guard let sizeGiB = UInt64(sizeText), sizeGiB >= 64 else {
                throw InstallerError.invalidDiskSize
            }
            let image = try await restoreImage(source)
            try await install(image: image, bundle: bundle, diskSizeGiB: sizeGiB)
        default:
            throw InstallerError.usage("Unknown command: \(command)")
        }
    }

    private static func option(_ name: String, in arguments: [String]) throws -> String {
        guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
            throw InstallerError.usage("Missing required option: \(name)")
        }
        return arguments[index + 1]
    }

    private static func optionalOption(_ name: String, in arguments: [String]) -> String? {
        guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
            return nil
        }
        return arguments[index + 1]
    }

    private static func restoreImage(_ source: String) async throws -> VZMacOSRestoreImage {
        if source == "latest" {
            return try await VZMacOSRestoreImage.latestSupported
        }
        return try await VZMacOSRestoreImage.image(
            from: URL(fileURLWithPath: source).standardizedFileURL
        )
    }

    private static func requirements(
        _ image: VZMacOSRestoreImage
    ) throws -> VZMacOSConfigurationRequirements {
        guard let requirements = image.mostFeaturefulSupportedConfiguration else {
            throw InstallerError.unsupportedRestoreImage
        }
        return requirements
    }

    private static func restoreRecord(
        _ image: VZMacOSRestoreImage
    ) throws -> RestoreImageRecord {
        let requirements = try requirements(image)
        return RestoreImageRecord(
            source: image.url.absoluteString,
            minimumCPUCount: requirements.minimumSupportedCPUCount,
            minimumMemoryBytes: requirements.minimumSupportedMemorySize,
            hardwareModelBase64: requirements.hardwareModel.dataRepresentation.base64EncodedString()
        )
    }

    @MainActor
    private static func install(
        image: VZMacOSRestoreImage,
        bundle: URL,
        diskSizeGiB: UInt64
    ) async throws {
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: bundle.path) {
            throw InstallerError.destinationExists(bundle.path)
        }
        try fileManager.createDirectory(
            at: bundle,
            withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700]
        )
        do {
            let requirements = try requirements(image)
            let auxiliaryURL = bundle.appendingPathComponent("AuxiliaryStorage")
            let diskURL = bundle.appendingPathComponent("Disk.img")
            let machineIdentifier = VZMacMachineIdentifier()
            let networkAddress = NetworkIdentity.generate()

            let auxiliary = try VZMacAuxiliaryStorage(
                creatingStorageAt: auxiliaryURL,
                hardwareModel: requirements.hardwareModel,
                options: []
            )
            try requirements.hardwareModel.dataRepresentation.write(
                to: bundle.appendingPathComponent("HardwareModel"),
                options: .atomic
            )
            try machineIdentifier.dataRepresentation.write(
                to: bundle.appendingPathComponent("MachineIdentifier"),
                options: .atomic
            )
            try Data((networkAddress + "\n").utf8).write(
                to: bundle.appendingPathComponent("NetworkMACAddress"),
                options: .atomic
            )
            fileManager.createFile(atPath: diskURL.path, contents: nil)
            let disk = try FileHandle(forWritingTo: diskURL)
            try disk.truncate(atOffset: diskSizeGiB * 1_024 * 1_024 * 1_024)
            try disk.close()

            let platform = VZMacPlatformConfiguration()
            platform.auxiliaryStorage = auxiliary
            platform.hardwareModel = requirements.hardwareModel
            platform.machineIdentifier = machineIdentifier

            let configuration = VZVirtualMachineConfiguration()
            configuration.platform = platform
            configuration.bootLoader = VZMacOSBootLoader()
            configuration.cpuCount = max(
                requirements.minimumSupportedCPUCount,
                min(
                    max(1, ProcessInfo.processInfo.processorCount - 1),
                    VZVirtualMachineConfiguration.maximumAllowedCPUCount
                )
            )
            configuration.memorySize = max(
                requirements.minimumSupportedMemorySize,
                4 * 1_024 * 1_024 * 1_024
            )
            configuration.storageDevices = [
                VZVirtioBlockDeviceConfiguration(
                    attachment: try VZDiskImageStorageDeviceAttachment(
                        url: diskURL,
                        readOnly: false
                    )
                )
            ]
            let graphics = VZMacGraphicsDeviceConfiguration()
            graphics.displays = [
                VZMacGraphicsDisplayConfiguration(
                    widthInPixels: 1920,
                    heightInPixels: 1200,
                    pixelsPerInch: 80
                )
            ]
            configuration.graphicsDevices = [graphics]
            let network = VZVirtioNetworkDeviceConfiguration()
            guard let macAddress = VZMACAddress(string: networkAddress) else {
                throw NetworkIdentityError.invalidFormat
            }
            network.macAddress = macAddress
            network.attachment = VZNATNetworkDeviceAttachment()
            configuration.networkDevices = [network]
            configuration.pointingDevices = [VZMacTrackpadConfiguration()]
            configuration.keyboards = [VZMacKeyboardConfiguration()]
            try configuration.validate()
            try configuration.validateSaveRestoreSupport()

            let virtualMachine = VZVirtualMachine(configuration: configuration)
            let installer = VZMacOSInstaller(
                virtualMachine: virtualMachine,
                restoringFromImageAt: image.url
            )
            Darwin.signal(SIGINT, SIG_IGN)
            let interrupt = DispatchSource.makeSignalSource(
                signal: SIGINT,
                queue: .main
            )
            interrupt.setEventHandler {
                installer.progress.cancel()
            }
            interrupt.resume()
            let observer = installer.progress.observe(
                \.fractionCompleted,
                options: [.initial, .new]
            ) { _, change in
                let record = InstallerProgressRecord(
                    event: "progress",
                    fractionCompleted: change.newValue
                )
                if let line = try? InstallerRecordEncoder.encode(record) {
                    print(line)
                    fflush(stdout)
                }
            }
            defer {
                observer.invalidate()
                interrupt.cancel()
                Darwin.signal(SIGINT, SIG_DFL)
            }
            do {
                try await installer.install()
            } catch {
                if installer.progress.isCancelled {
                    throw CancellationError()
                }
                throw error
            }
            print(
                try InstallerRecordEncoder.encode(
                    InstallerProgressRecord(event: "complete", fractionCompleted: 1)
                )
            )
        } catch {
            try? fileManager.removeItem(at: bundle)
            throw error
        }
    }
}
