import Foundation

public enum NetworkIdentityError: Error, CustomStringConvertible, Equatable {
    case invalidFormat
    case multicast
    case globallyAdministered
    case insufficientMachineIdentifier

    public var description: String {
        switch self {
        case .invalidFormat:
            return "Network MAC address must contain six hexadecimal octets."
        case .multicast:
            return "Network MAC address must be unicast."
        case .globallyAdministered:
            return "Network MAC address must be locally administered."
        case .insufficientMachineIdentifier:
            return "Machine identifier data is too short to derive a network identity."
        }
    }
}

public enum NetworkIdentity {
    public static func validate(_ value: String) throws -> String {
        let components = value.trimmingCharacters(in: .whitespacesAndNewlines)
            .split(separator: ":", omittingEmptySubsequences: false)
        guard components.count == 6 else {
            throw NetworkIdentityError.invalidFormat
        }
        let bytes = try components.map { component -> UInt8 in
            guard component.count == 2, let value = UInt8(component, radix: 16) else {
                throw NetworkIdentityError.invalidFormat
            }
            return value
        }
        guard bytes[0] & 0x01 == 0 else {
            throw NetworkIdentityError.multicast
        }
        guard bytes[0] & 0x02 == 0x02 else {
            throw NetworkIdentityError.globallyAdministered
        }
        return format(bytes)
    }

    public static func generate() -> String {
        var generator = SystemRandomNumberGenerator()
        var bytes = (0..<6).map { _ in UInt8.random(in: .min ... .max, using: &generator) }
        bytes[0] = (bytes[0] | 0x02) & 0xFE
        return format(bytes)
    }

    public static func derive(machineIdentifierData: Data) throws -> String {
        guard machineIdentifierData.count >= 6 else {
            throw NetworkIdentityError.insufficientMachineIdentifier
        }
        var bytes = Array(machineIdentifierData.prefix(6))
        bytes[0] = (bytes[0] | 0x02) & 0xFE
        return format(bytes)
    }

    private static func format(_ bytes: [UInt8]) -> String {
        bytes.map { String(format: "%02x", $0) }.joined(separator: ":")
    }
}
