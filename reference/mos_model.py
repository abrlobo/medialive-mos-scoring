"""Reference implementation of the MOS-Audio and MOS-Video models.

This is the authoritative implementation. Every number published in the README
and the companion blog post is computed from this module rather than typed by
hand; run verify.py to re-derive them.

The CloudWatch Metric Math expressions in ../metric-math/ mirror these
functions. If you change a coefficient here, change it there too.

Audio follows ITU-T G.107 (the E-Model) adapted for broadcast AAC: penalties in
R-factor points subtract from a 93.2 base, then R maps to MOS.
Video uses a weighted composite of five 0-1 component scores.
"""


def ie_from_plr(plr_pct):
    """E-Model equipment impairment factor. AAC 128 kbps: Ie_max=30, Bpl=10."""
    if plr_pct <= 0:
        return 0.0
    return (30.0 * plr_pct) / (plr_pct + 10.0)


def fill_penalty(fill_msec):
    return min(fill_msec / 60000.0, 1.0) * 20.0


def loudness_penalty(lkfs_avg, target=-23.0):
    return min(abs(lkfs_avg - target) / 6.0, 1.0) * 10.0


def silence_clip_penalty(dbfs_min, dbfs_max):
    return (5.0 if dbfs_min <= -60 else 0.0) + (5.0 if dbfs_max >= -1 else 0.0)


def r_factor(ie, fp, adp, scp):
    return max(0.0, min(100.0, 93.2 - ie - fp - adp - scp))


def mos_from_r(r):
    mos = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6
    return max(1.0, min(4.5, mos))


def mos_audio(plr_pct, fill_msec, lkfs_avg, dbfs_min=-20.0, dbfs_max=-6.0):
    """Returns (MOS, dict of component terms)."""
    ie = ie_from_plr(plr_pct)
    fp = fill_penalty(fill_msec)
    adp = loudness_penalty(lkfs_avg)
    scp = silence_clip_penalty(dbfs_min, dbfs_max)
    r = r_factor(ie, fp, adp, scp)
    return mos_from_r(r), {"Ie": ie, "FP": fp, "ADP": adp, "SCP": scp, "R": r,
                          "PLR": plr_pct}


def mos_video(dropped_frames=0, fill_msec=0, svq_time=0, fps=30, window_s=60,
              mqcs_vfd=None, mqcs_freeze=None, mqcs_svq=None,
              mqcs_black=None, mqcs_fill=None, mqcs_cc=None, min_mqcs=None):
    """Weighted composite video model. MQCS inputs default to best-case when absent."""
    drop_rate = dropped_frames / float(fps * window_s) if dropped_frames > 0 else 0.0
    vfd_norm = (100 - mqcs_vfd) / 100.0 if mqcs_vfd is not None else 0.0
    fds = 1 - min(1.0, drop_rate * 0.5 + vfd_norm * 0.5)

    freeze_norm = mqcs_freeze / 100.0 if mqcs_freeze is not None else 1.0
    fill_pen = min(1.0, fill_msec / 30000.0)
    ffs = freeze_norm * 0.7 + (1 - fill_pen) * 0.3

    svq_norm = mqcs_svq / 100.0 if mqcs_svq is not None else 1.0
    eqs = (1 - min(1.0, svq_time / 100.0)) * 0.5 + svq_norm * 0.5

    black_norm = mqcs_black / 100.0 if mqcs_black is not None else 1.0
    fillfr_norm = mqcs_fill / 100.0 if mqcs_fill is not None else 1.0
    cc_norm = mqcs_cc / 100.0 if mqcs_cc is not None else 1.0
    cis = black_norm * 0.35 + fillfr_norm * 0.35 + cc_norm * 0.30

    mns = min_mqcs / 100.0 if min_mqcs is not None else 1.0

    vqi = fds * 0.35 + ffs * 0.25 + eqs * 0.20 + cis * 0.15 + mns * 0.05
    mos = max(1.0, min(4.5, 1.0 + pow(vqi, 0.9) * 3.5))
    return mos, {"FDS": fds, "FFS": ffs, "EQS": eqs, "CIS": cis, "MNS": mns,
                 "VQI": vqi}


def band(mos):
    if mos >= 4.3:
        return "Excellent"
    if mos >= 4.0:
        return "Good"
    if mos >= 3.5:
        return "Fair"
    if mos >= 3.0:
        return "Poor"
    return "Bad"
