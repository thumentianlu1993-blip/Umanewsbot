import Foundation
import Vision
import AppKit

if CommandLine.arguments.count < 2 {
    fputs("usage: ocr_image.swift IMAGE...\n", stderr)
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["en-US", "en-GB"]

func jsonString(_ value: String) -> String {
    var output = "\""
    for scalar in value.unicodeScalars {
        switch scalar {
        case "\"":
            output += "\\\""
        case "\\":
            output += "\\\\"
        case "\n":
            output += "\\n"
        case "\r":
            output += "\\r"
        case "\t":
            output += "\\t"
        default:
            output.unicodeScalars.append(scalar)
        }
    }
    output += "\""
    return output
}

for imagePath in CommandLine.arguments.dropFirst() {
    let url = URL(fileURLWithPath: imagePath)
    guard let image = NSImage(contentsOf: url),
          let tiffData = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiffData),
          let cgImage = bitmap.cgImage else {
        fputs("failed to read image: \(imagePath)\n", stderr)
        continue
    }
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
        print("=== \(imagePath) ===")
        let observations = request.results ?? []
        for observation in observations {
            if let candidate = observation.topCandidates(1).first {
                let box = observation.boundingBox
                print("{\"text\":\(jsonString(candidate.string)),\"x\":\(box.minX),\"y\":\(box.minY),\"w\":\(box.width),\"h\":\(box.height)}")
            }
        }
    } catch {
        fputs("ocr failed for \(imagePath): \(error)\n", stderr)
    }
}
