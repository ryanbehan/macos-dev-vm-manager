// Portions adapted from Apple sample code. See THIRD_PARTY_NOTICES.md.

import Foundation

struct VMPaths {
    let bundle: URL
    let controlDirectory: URL

    var auxiliaryStorage: URL { bundle.appendingPathComponent("AuxiliaryStorage") }
    var diskImage: URL { bundle.appendingPathComponent("Disk.img") }
    var hardwareModel: URL { bundle.appendingPathComponent("HardwareModel") }
    var machineIdentifier: URL { bundle.appendingPathComponent("MachineIdentifier") }
    var networkMACAddress: URL { bundle.appendingPathComponent("NetworkMACAddress") }
    var saveFile: URL { bundle.appendingPathComponent("SaveFile.vzvmsave") }
    var runtimeFile: URL { controlDirectory.appendingPathComponent("runtime.json") }
    var controlResponseFile: URL { controlDirectory.appendingPathComponent("control-response.json") }
}
