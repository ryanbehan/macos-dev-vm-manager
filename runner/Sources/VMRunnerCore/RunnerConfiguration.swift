import Foundation

public enum RunnerConfigurationError: Error, CustomStringConvertible, Equatable {
    case missingOption(String)
    case unknownOption(String)

    public var description: String {
        switch self {
        case .missingOption(let option):
            return "Missing required option: \(option)"
        case .unknownOption(let option):
            return "Unknown option: \(option)"
        }
    }
}
public struct RunnerConfiguration: Equatable, Sendable {
    public let vmBundle: URL
    public let controlDirectory: URL

    public init(vmBundle: URL, controlDirectory: URL) {
        self.vmBundle = vmBundle
        self.controlDirectory = controlDirectory
    }

    public static func parse(arguments: [String]) throws -> RunnerConfiguration {
        var vmBundle: URL?
        var controlDirectory: URL?
        var index = 0
        while index < arguments.count {
            let option = arguments[index]
            guard index + 1 < arguments.count else {
                throw RunnerConfigurationError.missingOption(option)
            }
            let value = arguments[index + 1]
            switch option {
            case "--vm-bundle":
                vmBundle = URL(fileURLWithPath: value, isDirectory: true)
            case "--control-dir":
                controlDirectory = URL(fileURLWithPath: value, isDirectory: true)
            default:
                throw RunnerConfigurationError.unknownOption(option)
            }
            index += 2
        }
        guard let vmBundle else {
            throw RunnerConfigurationError.missingOption("--vm-bundle")
        }
        guard let controlDirectory else {
            throw RunnerConfigurationError.missingOption("--control-dir")
        }
        return RunnerConfiguration(
            vmBundle: vmBundle.standardizedFileURL,
            controlDirectory: controlDirectory.standardizedFileURL
        )
    }
}
