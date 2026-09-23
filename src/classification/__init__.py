"""완성 조립체 사진 한 장 → 어느 레시피(model_a/b/c)로 조립됐는지 분류하는 딥러닝 트랙.

디텍션(YOLO-OBB) 트랙과는 별개다. 디텍션은 조립 중 매 프레임 "무엇이 어디에" 를 보고,
이 분류기는 조립이 끝난 뒤 사진 한 장으로 "완성체가 어느 사양인가" 를 답한다.
룰베이스(구멍 개수 세기)와 대조하는 이중 검증용이며, 어디가 틀렸는지는 설명하지 않는다.

    python -m src.classification.train    --data ..\\aabb --out model\\classifier_resnet18.pt
    python -m src.classification.evaluate --weights model\\classifier_resnet18.pt --data ..\\aabb --gradcam 6

코드에서:
    from src.classification import Classifier
    clf = Classifier.load("model/classifier_resnet18.pt")
    r = clf.predict(frame_bgr)          # OpenCV 프레임, PIL 이미지, 파일 경로 모두 받는다
    r.label, r.recipe_id, r.confidence, r.unknown

torch 가 없는 환경에서도 이 패키지의 dataset/decide 는 import 된다 (torch 는 train/predict 안에서만 쓴다).
"""
from .dataset import Sample, class_names, load_settings, scan, split
from .predict import Classifier, ClassifyResult, decide

__all__ = ["Sample", "scan", "split", "class_names", "load_settings", "Classifier", "ClassifyResult", "decide"]
