# ATLAS Phase 13 Visual Perception Specification
## UI Detection, Visual Anomaly Detection & State Comparisons

---

## 1. Visual Observation Data Model

Every visual observation captured by an ATLAS worker must record:

```json
{
  "observation_id": "obs_vis_7894a",
  "worker_id": "worker_win11_01",
  "task_id": "task_e2e_checkout",
  "timestamp": 1731795000.125,
  "viewport": {
    "width": 1920,
    "height": 1080,
    "device_pixel_ratio": 1.25
  },
  "image": {
    "artifact_ref": "artifacts/task_e2e_checkout/screenshots/step_01.png",
    "width": 2400,
    "height": 1350,
    "format": "image/png"
  },
  "detected_elements": [
    {
      "element_id": "elem_btn_checkout",
      "type": "BUTTON",
      "label": "Complete Order",
      "bounding_box": {
        "ymin": 0.82,
        "xmin": 0.70,
        "ymax": 0.88,
        "xmax": 0.90
      },
      "confidence": 0.98,
      "is_clickable": true,
      "is_visible": true
    }
  ],
  "ocr_text_blocks": [
    {
      "text": "Total: $142.50",
      "bounding_box": { "ymin": 0.75, "xmin": 0.70, "ymax": 0.79, "xmax": 0.85 },
      "confidence": 0.99
    }
  ],
  "visual_state_hash": "sha256:d8a4f...",
  "status": "PROCESSED"
}
```

---

## 2. Visual State Comparison & Anomaly Detection

- **Visual State Hash**: Fast pHash or perceptual block hashing of the viewport screenshot detects unexpected changes (popups, captchas, error toasts).
- **Region of Interest (ROI)**: Isolates dynamic subregions (e.g. status bar, loading spinners) without re-analyzing static backgrounds.
- **Visual Anomaly Trigger**: If an unhandled modal or visual anomaly is detected, the perception engine halts the autonomous loop and requests either a replan or human approval.
