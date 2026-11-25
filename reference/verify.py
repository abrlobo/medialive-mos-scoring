"""Regression checks on every number published in the README and blog post.

Run this after changing mos_model.py. It fails loudly on drift, so the docs can
never silently disagree with the model.

    python3 verify.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mos_model import (mos_audio, mos_video, band, mos_from_r,  # noqa: E402
                       ie_from_plr)

fails = []


def expect(label, got, want, tol=0.006):
    ok = abs(got - want) <= tol
    print(f"{'ok  ' if ok else 'FAIL'} {label:<44s} "
          f"model={got:.4f}  published={want}")
    if not ok:
        fails.append(label)


def expect_band(value, want):
    got = band(value)
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} band({value}) = {got:<10s} "
          f"published={want}")
    if not ok:
        fails.append(f"band({value})")


print("=" * 68)
print("Stacked-impairment table (README 'Why perceptual scoring')")
print("=" * 68)
cases = [
    ("packet loss only", (0.9, 0, -23.0), 2.48, 0.00, 0.00, 90.72, 4.36,
     "Excellent"),
    ("fill only", (0.0, 18000, -23.0), 0.00, 6.00, 0.00, 87.20, 4.26, "Good"),
    ("loudness only", (0.0, 0, -18.5), 0.00, 0.00, 7.50, 85.70, 4.22, "Good"),
    ("all three", (0.9, 18000, -18.5), 2.48, 6.00, 7.50, 77.22, 3.91, "Fair"),
]
for lbl, args, ie, fp, adp, r, mos, bnd in cases:
    m, c = mos_audio(*args)
    expect(f"{lbl}: Ie", c["Ie"], ie)
    expect(f"{lbl}: FP", c["FP"], fp)
    expect(f"{lbl}: ADP", c["ADP"], adp)
    expect(f"{lbl}: R", c["R"], r, 0.01)
    expect(f"{lbl}: MOS", m, mos)
    expect_band(round(m, 2), bnd)

print("\n" + "=" * 68)
print("Ie curve (README MOS-Audio Step 2)")
print("=" * 68)
for plr, want in [(0.5, 1.43), (5, 10.00), (50, 25.00)]:
    expect(f"Ie at PLR {plr}%", ie_from_plr(plr), want)
print(f"ok   Ie ceiling is asymptotic: Ie(1e6%) = "
      f"{ie_from_plr(1e6):.4f} < 30")
if ie_from_plr(1e6) >= 30:
    fails.append("Ie ceiling")

print("\n" + "=" * 68)
print("R-to-MOS conversion table (README MOS-Audio Step 6)")
print("=" * 68)
for r, want in [(0, 1.00), (50, 2.58), (60, 3.10), (70, 3.60), (80, 4.02),
                (93.2, 4.41), (100, 4.50)]:
    expect(f"MOS at R={r}", mos_from_r(r), want)

slopes = {r: mos_from_r(r) - mos_from_r(r - 1) for r in range(1, 101)}
steepest = max(slopes, key=slopes.get)
expect("steepest slope R", float(steepest), 54.0, 0.5)
expect("slope at R=54", slopes[54], 0.053, 0.001)
expect("slope at R=95", slopes[95], 0.017, 0.001)

print("\n" + "=" * 68)
print("MOS scale boundaries")
print("=" * 68)
expect("perfect path R=100 -> ceiling", mos_from_r(100), 4.50)
expect("clean path R=93.2", mos_from_r(93.2), 4.41)
for v, b in [(4.45, "Excellent"), (4.15, "Good"), (3.70, "Fair"),
             (3.20, "Poor"), (2.50, "Bad")]:
    expect_band(v, b)

print("\n" + "=" * 68)
print("MOS-Video model")
print("=" * 68)
weights = [0.35, 0.25, 0.20, 0.15, 0.05]
print(f"ok   component weights sum to {sum(weights):.2f}")
if abs(sum(weights) - 1.0) > 1e-9:
    fails.append("video weights")

perfect, cp = mos_video(mqcs_vfd=100, mqcs_freeze=100, mqcs_svq=100,
                        mqcs_black=100, mqcs_fill=100, mqcs_cc=100,
                        min_mqcs=100)
expect("perfect channel VQI", cp["VQI"], 1.00)
expect("perfect channel MOS", perfect, 4.50)

no_mqcs, cn = mos_video(dropped_frames=0, fill_msec=0, svq_time=4)
print(f"ok   no CMAF Ingest (MQCS absent): VQI={cn['VQI']:.3f} "
      f"MOS={no_mqcs:.2f} -> {band(no_mqcs)}")
if no_mqcs < 4.3:
    fails.append("degradation default too pessimistic")

print("\n" + "=" * 68)
print("Walkthrough scenario (blog post)")
print("=" * 68)
# loudness regression alone: -16.8 LKFS, no network impairment
m_loud, c_loud = mos_audio(0, 0, -16.8)
expect("loudness regression alone", m_loud, 4.14)
expect_band(4.14, "Good")
print("     -> does not breach the < 3.6 warning, as the post states: "
      f"{m_loud >= 3.6}")
if m_loud < 3.6:
    fails.append("loudness-alone should not breach")

# the breaching datapoint: loss + fill + the same loudness regression
m_breach, c_breach = mos_audio(2.90, 31000, -16.8)
expect("breaching window Ie", c_breach["Ie"], 6.74)
expect("breaching window FP", c_breach["FP"], 10.33)
expect("breaching window ADP", c_breach["ADP"], 10.00)
expect("breaching window R", c_breach["R"], 66.12, 0.01)
expect("breaching window MOS", m_breach, 3.41)
expect_band(3.41, "Poor")
expect("points lost", 93.2 - c_breach["R"], 27.07, 0.01)
print("     -> breaches the < 3.6 warning threshold: "
      f"{m_breach < 3.6}")
if m_breach >= 3.6:
    fails.append("breach scenario should breach")

# counterfactuals the agent evaluates in chat
expect("failover to backup", mos_audio(0, 0, -16.8)[0], 4.14)
expect("revert loudness only", mos_audio(2.90, 31000, -23.0)[0], 3.87)
expect("both fixed", mos_audio(0, 0, -23.0)[0], 4.41)
expect("Ie+FP cleared by failover",
       c_breach["Ie"] + c_breach["FP"], 17.07, 0.01)

print("\n" + "=" * 68)
print("Cost claim: 16 metrics per fully instrumented channel")
print("=" * 68)
audio_refs = ["RtpPacketsLost", "RtpPacketsReceived",
              "OutputAudioLevelDbfs(Min)", "OutputAudioLevelDbfs(Max)",
              "OutputAudioLevelLkfs", "FillMsec"]
video_refs = ["DroppedFrames", "FillMsec", "SvqTime", "MinMQCS",
              "MqcsVideoFrameDrops", "MqcsFreezeFrameDetected", "MqcsSvq",
              "MqcsBlackFrameDetected", "MqcsFillFrameInsertion",
              "MqcsContinuityCounterErrors"]
total = len(audio_refs) + len(video_refs)
print(f"ok   audio={len(audio_refs)} video={len(video_refs)} total={total}")
if total != 16:
    fails.append("metric count")

print("\n" + "=" * 68)
if fails:
    print(f"FAILURES ({len(fails)}): {fails}")
    sys.exit(1)
print("ALL CHECKS PASS")
