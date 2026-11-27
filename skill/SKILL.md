---
name: medialive-mos-scoring
version: 1.0.0
description: >
  Derives Mean Opinion Score (MOS) for audio and video quality from native AWS
  Elemental MediaLive CloudWatch metrics using ITU-T E-Model principles adapted
  for broadcast and live-streaming environments. Use for MediaLive audio or
  video quality degradation, MOS computation, LKFS/dBFS loudness analysis,
  dropped frames, FillMsec, SvqTime, MQCS sub-scores, and CloudWatch Metric
  Math generation.
domain: medialive, mos, quality, video, audio, cloudwatch, broadcast
---

# MediaLive MOS Scoring

## What this skill does

1. Collect the correct native MediaLive CloudWatch metrics for audio and video
   quality assessment, using the right statistic for each.
2. Compute **MOS-Audio** (1.0–4.5) using the ITU-T G.107 E-Model with
   MediaLive-specific proxy signals.
3. Compute **MOS-Video** (1.0–4.5) using a VMAF-inspired weighted composite.
4. Build ready-to-deploy CloudWatch Metric Math expressions for both scores.
5. Configure CloudWatch alarms with warning and critical thresholds.
6. Diagnose a degraded score using a structured decision tree.

## Trigger phrases

Use this skill when the user asks about any of:

- MediaLive audio quality or video quality
- MOS score for live streaming; Mean Opinion Score from CloudWatch
- `OutputAudioLevelLkfs` / `OutputAudioLevelDbfs` analysis
- `DroppedFrames` / `FillMsec` / `SvqTime` interpretation
- MQCS metrics (`MinMQCS`, `MqcsFreezeFrameDetected`, and related)
- Broadcast loudness compliance (EBU R 128, LKFS)
- ITU-T E-Model for AWS MediaLive
- Live streaming quality degradation troubleshooting

## MOS scale

| MOS | Perception | Action |
|---|---|---|
| 4.3 – 4.5 | Excellent | None |
| 4.0 – 4.3 | Good | Monitor |
| 3.5 – 4.0 | Fair | Investigate |
| 3.0 – 3.5 | Poor | Immediate action |
| < 3.0 | Bad | Critical escalation |

Always report the numeric score **and** the band label.

## Metrics and required statistics

Using the wrong statistic produces a wrong score. These are not optional.

### Input health (MOS-Audio primary)

| Metric | Stat | Drives |
|---|---|---|
| `RtpPacketsLost` | Sum | packet loss rate (PLR) — E-Model `Ie` |
| `RtpPacketsReceived` | Sum | PLR denominator |
| `ChannelInputErrorSeconds` | Sum | fallback PLR for non-RTP inputs |
| `InputLossSeconds` | Sum | fallback for non-RTP inputs |
| `FillMsec` | Max | fill penalty — an average hides bursts |

### Audio output (MOS-Audio secondary)

| Metric | Stat | Drives |
|---|---|---|
| `OutputAudioLevelLkfs` | Average | loudness deviation from −23 LKFS |
| `OutputAudioLevelDbfs` | Min **and** Max | silence (≤ −60) and clipping (≥ −1) |

### Video output (MOS-Video)

| Metric | Stat | Drives |
|---|---|---|
| `DroppedFrames` | Sum | frame continuity (35%) |
| `FillMsec` | Max | freeze proxy |
| `SvqTime` | Max | encoder stress (20%) |

### MQCS sub-scores (require a CMAF Ingest output group)

| Metric | Stat | Weight |
|---|---|---|
| `MqcsVideoFrameDrops` | Min | 35% |
| `MqcsFreezeFrameDetected` | Min | 25% |
| `MqcsSvq` | Min | 20% |
| `MqcsBlackFrameDetected` | Min | 15% |
| `MqcsFillFrameInsertion` | Min | 15% |
| `MqcsContinuityCounterErrors` | Min | 15% |
| `MinMQCS` | Min | 5% |

## MOS-Audio formula

Penalties in R-factor points subtract from a 93.2 base. Larger is worse.

```
# Step 1 — packet loss rate
PLR = IF(RtpPacketsLost + RtpPacketsReceived > 0,
         RtpPacketsLost / (RtpPacketsLost + RtpPacketsReceived) * 100, 0)
# fallback: PLR = ChannelInputErrorSeconds / window_seconds * 100

# Step 2 — equipment impairment (AAC 128 kbps: Ie_max=30, Bpl=10)
Ie = (30 * PLR) / (PLR + 10)

# Step 3 — fill penalty, 0–20
FP = MIN(FillMsec_max / 60000, 1.0) * 20

# Step 4 — loudness deviation penalty, 0–10 (EBU R 128 target −23 LKFS)
ADP = MIN(ABS(LKFS_avg - (-23)) / 6.0, 1.0) * 10

# Step 5 — silence/clip penalty, 0 / 5 / 10
SCP = IF(dBFS_min <= -60, 5, 0) + IF(dBFS_max >= -1, 5, 0)

# Step 6 — rating factor and MOS
R = MAX(0, MIN(100, 93.2 - Ie - FP - ADP - SCP))
MOS_Audio = MAX(1.0, MIN(4.5, 1 + 0.035*R + R*(R-60)*(100-R)*7e-6))
```

**Always report the component terms alongside the score.** The decomposition
is usually the finding: a maxed `ADP` with near-zero `Ie` is a configuration
regression, not a network event, and the two have different owners.

## MOS-Video formula

Components are scores from 0 to 1, where 1.0 is unimpaired. Note this is the
opposite sign convention from the audio penalties.

```
# Frame Drop Score
drop_rate = DroppedFrames_sum / (FPS * window_seconds)
FDS = 1 - MIN(1, drop_rate*0.5 + ((100-MqcsVideoFrameDrops_min)/100)*0.5)

# Freeze Frame Score
FFS = (MqcsFreezeFrameDetected_min/100)*0.7
    + (1 - MIN(1, FillMsec_max/30000))*0.3

# Encoder Quality Score
EQS = (1 - MIN(1, SvqTime_max/100))*0.5 + (MqcsSvq_min/100)*0.5

# Content Integrity Score
CIS = (MqcsBlackFrameDetected_min/100)*0.35
    + (MqcsFillFrameInsertion_min/100)*0.35
    + (MqcsContinuityCounterErrors_min/100)*0.30

# MQCS normalised
MNS = MinMQCS_min / 100

VQI = FDS*0.35 + FFS*0.25 + EQS*0.20 + CIS*0.15 + MNS*0.05
MOS_Video = MAX(1.0, MIN(4.5, 1.0 + POW(VQI, 0.9) * 3.5))
```

`FPS` is the channel's output frame rate. Ask for it, or read it from the
channel configuration — do not assume 30.

## Diagnostics decision tree

Walk this and report the branch taken.

```
MOS-Audio < 3.6?
├── RtpPacketsLost > 0?
│   ├── YES → Is FEC functioning? (FecRowPacketsReceived > 0)
│   │         YES: upstream network degraded → engage upstream team
│   │         NO:  FEC misconfigured or absent → check RTP input FEC settings
│   └── NO  → FillMsec > 5000 ms?
│             YES: input is failing → check InputLossSeconds,
│                  PrimaryInputActive
│             NO:  LKFS deviation > 3 from −23?
│                  YES: loudness normalisation problem
│                  NO:  dBFS silence or clipping? → check audio routing/levels

MOS-Video < 3.5?
├── DroppedFrames > 0?
│   ├── YES → SvqTime > 20%?
│   │         YES: encoder overloaded → reduce encode complexity or
│   │              upgrade channel class
│   │         NO:  check NetworkIn for input starvation → investigate
│   │              upstream bandwidth
│   └── NO  → FillMsec > 5000 ms?
│             YES: input failing → check ChannelInputErrorSeconds,
│                  InputLossSeconds
│             NO:  MQCS sub-scores < 80?
│                  MqcsBlackFrameDetected: black frame in source feed
│                  MqcsFreezeFrameDetected: frozen frame in source feed
│                  MqcsContinuityCounterErrors: MPEG-TS stream corruption
```

Multiple branches can be true at once. Report each cause separately, ranked by
the points it cost, rather than forcing one narrative.

## Alarm thresholds

```yaml
MOS_Audio_Warning:   { Expression: MOS_A, Threshold: "< 3.6", Period: 60,
                       EvaluationPeriods: 3, TreatMissingData: notBreaching }
MOS_Audio_Critical:  { Expression: MOS_A, Threshold: "< 3.0", Period: 60,
                       EvaluationPeriods: 2, TreatMissingData: notBreaching }
MOS_Video_Warning:   { Expression: MOS_V, Threshold: "< 3.5", Period: 60,
                       EvaluationPeriods: 3, TreatMissingData: notBreaching }
MOS_Video_Critical:  { Expression: MOS_V, Threshold: "< 3.0", Period: 60,
                       EvaluationPeriods: 2, TreatMissingData: notBreaching }
```

Audio warns at 3.6, not 3.5, so the alarm fires while the score is still Fair
rather than at the Poor boundary; listeners notice dropouts and loudness faults
sooner than viewers notice mild video softness. Both critical alarms sit at 3.0.
When asked why the warning thresholds differ, give that reason.

## Graceful degradation

| Scenario | Missing metrics | Behaviour |
|---|---|---|
| Non-RTP input (HLS pull, UDP) | `RtpPackets*`, `Fec*` | PLR=0 baseline; use `ChannelInputErrorSeconds` fallback |
| No CMAF Ingest output group | All `Mqcs*` | MQCS terms default to 1.0 (best case); core video metrics still active |
| Single-pipeline channel | One pipeline set | Use that pipeline; take MIN across both if redundant |
| Audio-only channel | Video metrics | Compute MOS-Audio only; suppress MOS-Video |

When MQCS terms defaulted, say so. The score is then a floor on impairment,
not a complete picture, because source-side black frames and continuity errors
cannot be detected.

## Evaluating a proposed remediation

When the user asks whether an action would help, recompute the score with that
one input changed and answer with the resulting number and band. Common cases:

- **Input failover** clears `Ie` and `FP` but not `ADP`, because loudness
  originates in the channel configuration rather than the input.
- **Raising a bitrate or channel class** affects `EQS` via `SvqTime`.
- **Reverting an audio normalisation change** clears `ADP` only.

State what the action does *not* fix.

## Reporting rules

1. Lead with the score and its band label.
2. Show the component decomposition.
3. Name the branch of the decision tree you took.
4. Rank multiple causes by points lost; give each its own evidence.
5. For each proposed mitigation, state the expected score after the change.
6. Note that these are engineering estimates, not ITU-T P.800 panel results,
   whenever the user treats a value as an absolute measure of quality.

## References

- [MediaLive input metrics](https://docs.aws.amazon.com/medialive/latest/ug/eml-metrics-input-metrics.html)
- [MediaLive output metrics](https://docs.aws.amazon.com/medialive/latest/ug/eml-metrics-output-metrics.html)
- [MediaLive MQCS metrics](https://docs.aws.amazon.com/medialive/latest/ug/eml-metrics-quality-score.html)
- ITU-T G.107 — The E-Model
- EBU R 128 — Loudness normalisation
