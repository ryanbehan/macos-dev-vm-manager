// Portions adapted from Apple sample code. See THIRD_PARTY_NOTICES.md.

import Foundation
import Virtualization
import VMRunnerCore

enum VMConfigurationError: Error, CustomStringConvertible {
    case missingArtifact(String)
    case invalidHardwareModel
    case unsupportedHardwareModel
    case invalidMachineIdentifier
    case invalidNetworkIdentity(String)

    var description: String {
        switch self {
        case .missingArtifact(let path): return "Missing VM artifact: \(path)"
        case .invalidHardwareModel: return "Invalid VM hardware model."
        case .unsupportedHardwareModel: return "The VM hardware model is unsupported on this host."
        case .invalidMachineIdentifier: return "Invalid VM machine identifier."
        case .invalidNetworkIdentity(let reason): return "Invalid VM network identity: \(reason)"
        }
    }
}

struct VMConfigurationBuilder {
    let paths: VMPaths

    func build() throws -> VZVirtualMachineConfiguration {
        let configuration = VZVirtualMachineConfiguration()
        configuration.platform = try makePlatform()
        configuration.bootLoader = VZMacOSBootLoader()

        var cpuCount = max(1, ProcessInfo.processInfo.processorCount - 1)
        cpuCount = max(cpuCount, VZVirtualMachineConfiguration.minimumAllowedCPUCount)
        cpuCount = min(cpuCount, VZVirtualMachineConfiguration.maximumAllowedCPUCount)
        configuration.cpuCount = cpuCount

        var memorySize = UInt64(4 * 1024 * 1024 * 1024)
        memorySize = max(memorySize, VZVirtualMachineConfiguration.minimumAllowedMemorySize)
        memorySize = min(memorySize, VZVirtualMachineConfiguration.maximumAllowedMemorySize)
        configuration.memorySize = memorySize

        configuration.storageDevices = [try makeStorageDevice()]
        configuration.graphicsDevices = [makeGraphicsDevice()]
        configuration.networkDevices = [try makeNetworkDevice()]
        configuration.audioDevices = [makeAudioDevice()]
        configuration.pointingDevices = [VZMacTrackpadConfiguration()]
        configuration.keyboards = [VZMacKeyboardConfiguration()]

        try configuration.validate()
        try configuration.validateSaveRestoreSupport()
        return configuration
    }

    private func makePlatform() throws -> VZMacPlatformConfiguration {
        let fileManager = FileManager.default
        for url in [paths.auxiliaryStorage, paths.hardwareModel, paths.machineIdentifier] {
            guard fileManager.fileExists(atPath: url.path) else {
                throw VMConfigurationError.missingArtifact(url.path)
            }
        }
        let hardwareData = try Data(contentsOf: paths.hardwareModel)
        guard let hardwareModel = VZMacHardwareModel(dataRepresentation: hardwareData) else {
            throw VMConfigurationError.invalidHardwareModel
        }
        guard hardwareModel.isSupported else {
            throw VMConfigurationError.unsupportedHardwareModel
        }
        let identifierData = try Data(contentsOf: paths.machineIdentifier)
        guard let identifier = VZMacMachineIdentifier(dataRepresentation: identifierData) else {
            throw VMConfigurationError.invalidMachineIdentifier
        }
        let platform = VZMacPlatformConfiguration()
        platform.auxiliaryStorage = VZMacAuxiliaryStorage(contentsOf: paths.auxiliaryStorage)
        platform.hardwareModel = hardwareModel
        platform.machineIdentifier = identifier
        return platform
    }

    private func makeStorageDevice() throws -> VZVirtioBlockDeviceConfiguration {
        guard FileManager.default.fileExists(atPath: paths.diskImage.path) else {
            throw VMConfigurationError.missingArtifact(paths.diskImage.path)
        }
        let attachment = try VZDiskImageStorageDeviceAttachment(
            url: paths.diskImage,
            readOnly: false
        )
        return VZVirtioBlockDeviceConfiguration(attachment: attachment)
    }

    private func makeGraphicsDevice() -> VZMacGraphicsDeviceConfiguration {
        let graphics = VZMacGraphicsDeviceConfiguration()
        graphics.displays = [
            VZMacGraphicsDisplayConfiguration(
                widthInPixels: 1920,
                heightInPixels: 1200,
                pixelsPerInch: 80
            )
        ]
        return graphics
    }

    private func makeNetworkDevice() throws -> VZVirtioNetworkDeviceConfiguration {
        let address: String
        do {
            if FileManager.default.fileExists(atPath: paths.networkMACAddress.path) {
                address = try NetworkIdentity.validate(
                    String(contentsOf: paths.networkMACAddress, encoding: .utf8)
                )
            } else {
                address = try NetworkIdentity.derive(
                    machineIdentifierData: Data(contentsOf: paths.machineIdentifier)
                )
            }
        } catch {
            throw VMConfigurationError.invalidNetworkIdentity(String(describing: error))
        }
        guard let macAddress = VZMACAddress(string: address) else {
            throw VMConfigurationError.invalidNetworkIdentity(address)
        }
        let network = VZVirtioNetworkDeviceConfiguration()
        network.macAddress = macAddress
        network.attachment = VZNATNetworkDeviceAttachment()
        return network
    }

    private func makeAudioDevice() -> VZVirtioSoundDeviceConfiguration {
        let audio = VZVirtioSoundDeviceConfiguration()
        let output = VZVirtioSoundDeviceOutputStreamConfiguration()
        output.sink = VZHostAudioOutputStreamSink()
        audio.streams = [output]
        return audio
    }
}
