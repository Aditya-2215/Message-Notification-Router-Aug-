# Message Notification Router — Personalized Multimodal Baseline

This package is based on the uploaded `code(5).zip` implementation and improves its routing logic, especially exact phrase matching, urgent group messages, multimodal handling, business safety advisories, and user/group-level dismissal behavior.

## Run

Keep the supplied `dataset/` folder beside this README:

```bash
python -m pip install -r code/requirements.txt
python code/main.py --dataset dataset --output output.csv
```

The output has exactly these columns in order:

```text
message_id,action,message_type,reason,confidence,evidence_message_ids
```

## Evaluation against the provided labeled sample

The included evaluation helper runs the same routing engine over `dataset/sample_messages.csv` and compares `action` and `message_type` to its labels:

```bash
python code/evaluation/main.py --dataset dataset
```

The latest local check of the 30 labeled sample rows achieved **96.7% action agreement** and **93.3% message-type agreement**. This is a small sample check, not a guarantee of hidden-test accuracy. Two voice-note examples remained uncertain because their content was not transcribed in this runtime; the code supports optional local ASR.

## Features

- User, group, business-account, opt-in, dismissal, quiet-hours, and notification-load context.
- Retrieval of related historical message IDs as evidence.
- Whole-word and phrase matching to avoid accidental matches (for example, `fee` inside `feedback`).
- Scam/suspicious-link overrides and handling of benign security advisories.
- Image OCR using Pillow + pytesseract, when installed with the Tesseract executable.
- Optional voice transcription through `faster-whisper`. It loads a model once and reuses it. Set `WHISPER_MODEL` to choose a model; the first run may require model download access.
- Deterministic CSV output validation for row count and allowed values.

## Dependencies

Core: `pandas`.

Optional image OCR:
- `Pillow`
- `pytesseract`
- System Tesseract OCR installation

Optional voice ASR:
- `faster-whisper` (model files are downloaded/cached by its runtime as needed)

## Important limitation

No system can honestly promise 100% accuracy on hidden labels. This is a transparent heuristic baseline; high-stakes deployment needs labeled validation, careful threshold calibration, and multimodal coverage checks.
