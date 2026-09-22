from src.contracts.detections import DetectionFrame, OBBDetection


def from_ultralytics(result, frame_id: int, timestamp_ms: float, class_mapping=None) -> DetectionFrame:
    """One Results object, with OBB xywhr already in original-image pixels.

    Caller supplies capture time, not a model-local timing value. No inference
    or recipe logic is performed here. Class names must match the five classes.
    """
    if result.obb is None:
        raise ValueError("An OBB model result is required")
    boxes = result.obb.xywhr.cpu().tolist()
    classes = result.obb.cls.cpu().tolist()
    confidences = result.obb.conf.cpu().tolist()
    if not len(boxes) == len(classes) == len(confidences):
        raise ValueError("Mismatched OBB output lengths")
    mapping = class_mapping or {}
    detections = tuple(OBBDetection(str(i), mapping.get(result.names[int(class_id)], result.names[int(class_id)]), confidence,
                                   (box[0], box[1]), box[2], box[3], box[4])
                       for i, (box, class_id, confidence) in enumerate(zip(boxes, classes, confidences)))
    return DetectionFrame(frame_id, timestamp_ms, detections)
