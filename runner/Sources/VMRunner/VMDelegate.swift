// Portions adapted from Apple sample code. See THIRD_PARTY_NOTICES.md.

import Foundation
import Virtualization

final class VMDelegate: NSObject, VZVirtualMachineDelegate {
    var didStop: (() -> Void)?
    var didStopWithError: ((Error) -> Void)?

    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        didStop?()
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        didStopWithError?(error)
    }
}
