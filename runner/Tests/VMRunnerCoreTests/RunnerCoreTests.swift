import Foundation
import Testing
@testable import VMRunnerCore

@Test func parsesRequiredArguments() throws {
    let configuration = try RunnerConfiguration.parse(arguments: [
        "--vm-bundle", "/tmp/VM.bundle",
        "--control-dir", "/tmp/vmctl-state",
    ])
    #expect(configuration.vmBundle.path == "/tmp/VM.bundle")
    #expect(configuration.controlDirectory.path == "/tmp/vmctl-state")
}

@Test func rejectsMissingArguments() {
    #expect(throws: RunnerConfigurationError.missingOption("--control-dir")) {
        try RunnerConfiguration.parse(arguments: ["--vm-bundle", "/tmp/VM.bundle"])
    }
}

@Test func writesAtomicRuntimeRecord() throws {
    let directory = FileManager.default.temporaryDirectory
        .appendingPathComponent(UUID().uuidString, isDirectory: true)
    let url = directory.appendingPathComponent("runtime.json")
    defer { try? FileManager.default.removeItem(at: directory) }
    let record = RuntimeRecord(
        pid: 42,
        state: "running",
        vmBundle: "/tmp/VM.bundle",
        updatedAt: "2026-07-18T00:00:00Z"
    )
    try AtomicRecordWriter().write(record, to: url)
    let decoded = try JSONDecoder().decode(RuntimeRecord.self, from: Data(contentsOf: url))
    #expect(decoded == record)
}

@Test func mapsControlSignalsToDarwinUserSignals() {
    #expect(ControlSignal.shutdown.rawValue == SIGUSR1)
    #expect(ControlSignal.suspend.rawValue == SIGUSR2)
}

@Test func validatesAndGeneratesLocalUnicastNetworkIdentity() throws {
    let generated = NetworkIdentity.generate()
    #expect(try NetworkIdentity.validate(generated) == generated)
    let first = UInt8(generated.prefix(2), radix: 16)!
    #expect(first & 0x01 == 0)
    #expect(first & 0x02 == 0x02)
    #expect(throws: NetworkIdentityError.multicast) {
        try NetworkIdentity.validate("03:00:00:00:00:01")
    }
    #expect(throws: NetworkIdentityError.globallyAdministered) {
        try NetworkIdentity.validate("00:00:00:00:00:01")
    }
}

@Test func derivesStableLegacyNetworkIdentity() throws {
    let data = Data([0, 1, 2, 3, 4, 5, 6, 7])
    let first = try NetworkIdentity.derive(machineIdentifierData: data)
    let second = try NetworkIdentity.derive(machineIdentifierData: data)
    #expect(first == second)
    #expect(first == "02:01:02:03:04:05")
}
