// Records what the Mac is playing (all processes) to a 16-bit mono WAV via
// a Core Audio process tap (macOS 14.2+). Usage: system-audio-capture <out.wav>
//
// Prints "ready <rate>" once capture starts, and "peak <0..1>" on exit so the
// caller can spot a silent capture (the system shows no error when the
// "System Audio Recording" permission is denied; the tap just delivers zeros).
// Stop with SIGINT or SIGTERM; the WAV header is rewritten every second so a
// crash still leaves a readable file.
//
// The tap delivers nothing while nothing plays, so gaps are filled with
// silence from the callback timestamps: sample N of the file is always N/rate
// seconds after "ready", which keeps it in step with the mic track.

import AudioToolbox
import CoreAudio
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

func check(_ status: OSStatus, _ what: String) {
    if status != noErr { fail("\(what) failed (OSStatus \(status))") }
}

func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )
}

func defaultOutputDeviceUID() -> String {
    var device = AudioObjectID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var addr = address(kAudioHardwarePropertyDefaultSystemOutputDevice)
    check(
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &device),
        "reading the default output device"
    )
    var uid: Unmanaged<CFString>?
    size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    addr = address(kAudioDevicePropertyDeviceUID)
    check(AudioObjectGetPropertyData(device, &addr, 0, nil, &size, &uid), "reading the output device UID")
    guard let uid else { fail("output device has no UID") }
    return uid.takeRetainedValue() as String
}

final class WavWriter {
    private let handle: FileHandle
    private let rate: UInt32
    private var dataBytes: UInt32 = 0

    init(path: String, rate: UInt32) {
        guard FileManager.default.createFile(atPath: path, contents: nil),
              let handle = FileHandle(forWritingAtPath: path)
        else { fail("cannot write \(path)") }
        self.handle = handle
        self.rate = rate
        handle.write(header())
    }

    private func header() -> Data {
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + dataBytes)
        d.append(contentsOf: Array("WAVEfmt ".utf8)); u32(16)
        u16(1); u16(1)  // PCM, mono
        u32(rate); u32(rate * 2); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(dataBytes)
        return d
    }

    var frames: Int { Int(dataBytes / 2) }

    func append(_ samples: [Int16]) {
        samples.withUnsafeBufferPointer { handle.write(Data(buffer: $0)) }
        dataBytes += UInt32(samples.count * 2)
    }

    func appendSilence(_ count: Int) {
        if count > 0 { append([Int16](repeating: 0, count: count)) }
    }

    func flushHeader() {
        handle.seek(toFileOffset: 0)
        handle.write(header())
        handle.seekToEndOfFile()
    }

    func close() {
        flushHeader()
        try? handle.close()
    }
}

guard CommandLine.arguments.count == 2 else { fail("usage: system-audio-capture <out.wav>") }
let outPath = CommandLine.arguments[1]
let queue = DispatchQueue(label: "system-audio-capture")

// 1. a private tap on everything the system plays
let tapDescription = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tapDescription.uuid = UUID()
tapDescription.isPrivate = true
tapDescription.muteBehavior = .unmuted
var tapID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateProcessTap(tapDescription, &tapID), "creating the process tap")

var format = AudioStreamBasicDescription()
var formatSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
var formatAddr = address(kAudioTapPropertyFormat)
check(AudioObjectGetPropertyData(tapID, &formatAddr, 0, nil, &formatSize, &format), "reading the tap format")
guard format.mFormatID == kAudioFormatLinearPCM, format.mFormatFlags & kAudioFormatFlagIsFloat != 0,
      format.mBitsPerChannel == 32
else { fail("unexpected tap format: \(format)") }
let nonInterleaved = format.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
let channels = Int(max(format.mChannelsPerFrame, 1))

// 2. a private aggregate device that exposes the tap as an input
let outputUID = defaultOutputDeviceUID()
let aggregate: [String: Any] = [
    kAudioAggregateDeviceNameKey: "local-stt system audio",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceMainSubDeviceKey: outputUID,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
    kAudioAggregateDeviceTapListKey: [
        [kAudioSubTapDriftCompensationKey: true, kAudioSubTapUIDKey: tapDescription.uuid.uuidString],
    ],
]
var aggregateID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID), "creating the aggregate device")

// 3. stream the tap to disk as mono Int16
let rate = format.mSampleRate
let writer = WavWriter(path: outPath, rate: UInt32(rate))
var peak: Float = 0
var startNanos: UInt64 = 0
let gapTolerance = Int(rate / 50)  // 20ms: ignore callback timing jitter

func padSilence(untilNanos nanos: UInt64) {
    guard nanos > startNanos else { return }
    let expected = Int(Double(nanos - startNanos) / 1e9 * rate)
    let gap = expected - writer.frames
    if gap > gapTolerance { writer.appendSilence(gap) }
}

var procID: AudioDeviceIOProcID?
check(
    AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, queue) { _, input, inputTime, _, _ in
        if inputTime.pointee.mFlags.contains(.hostTimeValid) {
            padSilence(untilNanos: AudioConvertHostTimeToNanos(inputTime.pointee.mHostTime))
        }
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        guard let first = buffers.first, let firstData = first.mData else { return }
        var mono: [Int16]
        if nonInterleaved {
            let frames = Int(first.mDataByteSize) / 4
            mono = [Int16](repeating: 0, count: frames)
            let planes = buffers.compactMap { $0.mData?.assumingMemoryBound(to: Float.self) }
            for i in 0..<frames {
                var sum: Float = 0
                for p in planes { sum += p[i] }
                let v = sum / Float(planes.count)
                peak = max(peak, abs(v))
                mono[i] = Int16(max(-1, min(1, v)) * 32767)
            }
        } else {
            let samples = firstData.assumingMemoryBound(to: Float.self)
            let frames = Int(first.mDataByteSize) / (4 * channels)
            mono = [Int16](repeating: 0, count: frames)
            for i in 0..<frames {
                var sum: Float = 0
                for c in 0..<channels { sum += samples[i * channels + c] }
                let v = sum / Float(channels)
                peak = max(peak, abs(v))
                mono[i] = Int16(max(-1, min(1, v)) * 32767)
            }
        }
        writer.append(mono)
    },
    "creating the IO callback"
)
queue.sync {
    check(AudioDeviceStart(aggregateID, procID), "starting capture")
    startNanos = AudioConvertHostTimeToNanos(AudioGetCurrentHostTime())
}
print("ready \(Int(rate))")
fflush(stdout)

let headerTimer = DispatchSource.makeTimerSource(queue: queue)
headerTimer.schedule(deadline: .now() + 1, repeating: 1)
headerTimer.setEventHandler { writer.flushHeader() }
headerTimer.resume()

func shutdown() {
    AudioDeviceStop(aggregateID, procID)
    padSilence(untilNanos: AudioConvertHostTimeToNanos(AudioGetCurrentHostTime()))
    if let procID { AudioDeviceDestroyIOProcID(aggregateID, procID) }
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
    writer.close()
    print("peak \(peak)")
    fflush(stdout)
    exit(0)
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
let signalSources = [SIGINT, SIGTERM].map { sig -> DispatchSourceSignal in
    let source = DispatchSource.makeSignalSource(signal: sig, queue: queue)
    source.setEventHandler { shutdown() }
    source.resume()
    return source
}
dispatchMain()
