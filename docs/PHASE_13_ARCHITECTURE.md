# ATLAS Phase 13 Architecture Specification
## Multimodal Autonomous Perception & Intelligence Platform

---

## 1. High-Level Architectural Model

```
       +-------------------------------------------------------+
       |                  MULTIMODAL SENSORS                   |
       |  Screenshots | Video Streams | Audio | PDF Documents  |
       +---------------------------+---------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |             MULTIMODAL PERCEPTION ENGINE              |
       |  UI Detection | OCR | Bounding Boxes | Audio STT      |
       +---------------------------+---------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |                VISUAL GROUNDING SYSTEM                |
       |  Coord Transforms: Normalized -> Viewport -> Screen    |
       |  Stale Observation Guard (Age < 5s)                   |
       +---------------------------+---------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |             PERCEPTION-DRIVEN PLANNER                 |
       |  Hypothesize -> Ground Target -> Formulate Action     |
       +---------------------------+---------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |                 ATLAS ACTION FIREWALL                 |
       |  Mandatory Policy Verification: ALLOW | APPROVE | DENY|
       +---------------------------+---------------------------+
                                   |
                                   v
       +-------------------------------------------------------+
       |           DISTRIBUTED WORKER / DRIVER ENGINE          |
       |  Execute Action -> Capture Evidence -> Verify State   |
       +-------------------------------------------------------+
```

---

## 2. Core Subsystems

### 2.1 Multimodal Provider Abstraction (`atlas_multimodal.provider`)
- Defines standard interface for vision, audio, video, and document models.
- Declares explicit provider capabilities (`IMAGE_UNDERSTANDING`, `VIDEO_UNDERSTANDING`, `SPEECH_TO_TEXT`, `SPEECH_TO_SPEECH`, `DOCUMENT_OCR`, `STRUCTURED_OUTPUT`).
- Enforces model routing with automated fallback on provider timeout or failure.

### 2.2 Visual Perception & Grounding (`atlas_multimodal.visual` & `atlas_multimodal.grounding`)
- Normalizes bounding boxes to $[0, 1]$ coordinate space.
- Converts to viewport coordinates based on window size and device pixel ratio (DPR).
- Converts to operating system screen coordinates by adding window chrome and multi-monitor offsets.
- **Stale Observation Guard**: If observation timestamp is older than threshold (5.0s), the grounding system halts and demands fresh visual capture before action submission.

### 2.3 Audio & Video Intelligence (`atlas_multimodal.audio` & `atlas_multimodal.video`)
- Video processor extracts keyframes using adaptive scene change detection and sampling limits.
- Audio processor requires explicit consent tokens before microphone access; records timestamped transcriptions with speaker tags.

### 2.4 Document Intelligence (`atlas_multimodal.document`)
- Parses PDF structures, extracts tables with headers, OCRs embedded text, and extracts structured entities.
- Verifies decompression ratios to prevent compression bombs (`max_ratio = 100:1`).

### 2.5 Multimodal Memory & Isolation (`atlas_multimodal.memory`)
- Large binary artifacts (images, audio, video) are persisted via `ArtifactManager` to prevent bloating the relational database.
- Metadata and semantic embeddings are stored per tenant and task with strict tenant scoping.
