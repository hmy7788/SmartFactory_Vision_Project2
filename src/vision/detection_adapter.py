from src.contracts.detections import DetectionFrame, OBBDetection


def from_ultralytics(result, frame_id: int, timestamp_ms: float, class_mapping=None) -> DetectionFrame:
    """One Results object → DetectionFrame, in original-image pixels.

    OBB model  : result.obb.xywhr (angle in radians) is used as is.
    detect/AABB: result.boxes.xywh is used with angle 0. The core's major_axis() swaps
                 width/height for tall boxes, so an upright vertical part still reads as a
                 part at 90°. Tilt cannot be measured from an AABB — use
                 src.vision.angle_refiner.refine_angles on the frame for that.

    Caller supplies capture time, not a model-local timing value. No inference
    or recipe logic is performed here. Class names must match the five classes
    (either the model's own names or through class_mapping).
    """
    obb = getattr(result, "obb", None)
    if obb is not None:
        boxes = obb.xywhr.cpu().tolist()
        classes = obb.cls.cpu().tolist()
        confidences = obb.conf.cpu().tolist()
    else:
        bx = getattr(result, "boxes", None)
        if bx is None:
            raise ValueError("An OBB or detect model result is required")
        boxes = [[*b, 0.0] for b in bx.xywh.cpu().tolist()]
        classes = bx.cls.cpu().tolist()
        confidences = bx.conf.cpu().tolist()
    if not len(boxes) == len(classes) == len(confidences):
        raise ValueError("Mismatched detection output lengths")
    mapping = class_mapping or {}
    detections = tuple(OBBDetection(str(i), mapping.get(result.names[int(class_id)], result.names[int(class_id)]), confidence,
                                   (box[0], box[1]), box[2], box[3], box[4])
                       for i, (box, class_id, confidence) in enumerate(zip(boxes, classes, confidences)))
    return DetectionFrame(frame_id, timestamp_ms, detections)
