"""Newtone (Image-Line, FL Studio) saved-state codec. See docs/re-newtone.md.

Layout of the blob that TTestPlug.SaveRestoreState (FL event 213 / .fst plugin data) writes:

    u32 version = 0                (load rejects > 0)
    TLV*  [u32 tag][u64 len][len bytes]
      1  (0x28)  editor: i32 w, i32 h, u32 flags, u8 p24, u8 p23, 26 zero bytes
      2  (n)     TVSTPlugin chunk of the zplane/JUCE engine (Newtone_Engine_x64.dll, VST2):
                   i32 -9, u8 flags, i32 -2, i64 size, i32 program, size bytes:
                   'VC2!' u32 n  n bytes UTF-8 XML  0x00   (JUCE copyXmlToBinary)
      3  (n)     sample path of the loaded audio (FL-converted, may be relative), 1 byte per char
      4  (0xc)   i32 round(p5*8192), i32 round(p6*8192), i32 0   (engine params 5/6)
      5  (0x10)  i32 round(p16*16384), 12 zero bytes             (engine param 16)
      6  (0x20)  f32 p18, u32 bit0 = p17 == 1, 24 zero bytes     (engine params 18/17)

Unknown tags and every byte are kept, so decode() -> encode() is byte-exact.
The XML (root NewToneProject) holds Tracks/Trk_N (FilePath, AudioObject with Pitch_N notes).
"""
import re
import struct
import sys

JUCE_MAGIC = b"VC2!"


def tlv_parse(blob, start=4):
    out, o = [], start
    while o < len(blob):
        if o + 12 > len(blob):
            raise ValueError(f"truncated TLV header at {o}")
        tag, n = struct.unpack_from("<IQ", blob, o)
        o += 12
        if o + n > len(blob):
            raise ValueError(f"TLV {tag} overruns blob")
        out.append([tag, blob[o:o + n]])
        o += n
    return out


def tlv_pack(version, sections):
    return struct.pack("<I", version) + b"".join(struct.pack("<IQ", t, len(d)) + bytes(d) for t, d in sections)


class VstChunk:
    """Tag 2: FL's TVSTPlugin.SaveRestore layout around the engine's chunk."""

    def __init__(self, data):
        self.version, self.flags = struct.unpack_from("<iB", data, 0)
        if self.version != -9:
            raise ValueError(f"unexpected TVSTPlugin state version {self.version}")
        marker, = struct.unpack_from("<i", data, 5)
        if marker == -2:
            self.size, = struct.unpack_from("<q", data, 9)
            o = 17
        else:
            self.size, o = marker, 9
        self.marker = marker
        self.program, = struct.unpack_from("<i", data, o)
        o += 4
        self.chunk = data[o:o + self.size]
        self.tail = data[o + self.size:]

    def encode(self):
        head = struct.pack("<iB", self.version, self.flags)
        head += struct.pack("<iq", -2, len(self.chunk)) if self.marker == -2 else struct.pack("<i", len(self.chunk))
        return head + struct.pack("<i", self.program) + self.chunk + self.tail


def juce_xml(chunk):
    if chunk[:4] != JUCE_MAGIC:
        raise ValueError("engine chunk is not JUCE XML (VC2!)")
    n, = struct.unpack_from("<I", chunk, 4)
    return chunk[8:8 + n].decode("utf-8"), chunk[8 + n:]


def juce_chunk(xml_text, trailer=b"\0"):
    raw = xml_text.encode("utf-8")
    return JUCE_MAGIC + struct.pack("<I", len(raw)) + raw + trailer


class NewtoneState:
    def __init__(self, blob):
        self.version, = struct.unpack_from("<I", blob, 0)
        self.sections = tlv_parse(blob)
        self.vst = VstChunk(self.section(2)) if self.section(2) is not None else None
        self.xml, self.xml_trailer = juce_xml(self.vst.chunk) if self.vst else (None, b"")

    def section(self, tag):
        return next((d for t, d in self.sections if t == tag), None)

    def set_section(self, tag, data):
        for s in self.sections:
            if s[0] == tag:
                s[1] = data
                return
        self.sections.append([tag, data])

    def encode(self):
        if self.vst is not None:
            self.vst.chunk = juce_chunk(self.xml, self.xml_trailer)
            self.set_section(2, self.vst.encode())
        return tlv_pack(self.version, self.sections)

    # --- readable views ----------------------------------------------------------------------
    @property
    def sample_path(self):
        d = self.section(3)
        return d.decode("mbcs" if sys.platform == "win32" else "latin-1", "replace") if d else ""

    def editor(self):
        d = self.section(1)
        if not d:
            return {}
        w, h, flags, p24, p23 = struct.unpack_from("<iiIBB", d, 0)
        return {"width": w, "height": h, "flags": flags, "param24": p24, "param23": p23}

    def engine_params(self):
        out = {}
        d = self.section(4)
        if d:
            a, b, _ = struct.unpack_from("<iii", d, 0)
            out.update(param5=a / 8192.0, param6=b / 8192.0)
        d = self.section(5)
        if d:
            out["param16"] = struct.unpack_from("<i", d, 0)[0] / 16384.0
        d = self.section(6)
        if d:
            f, bits = struct.unpack_from("<fI", d, 0)
            out.update(param18=f, param17=bool(bits & 1))
        return out

    def notes(self):
        """[{track, index, **attributes as numbers}] of every Pitch_N element (one per note)."""
        return project_notes(self.xml or "")


# The project XML is read with regular expressions, not xml.etree: pyexpat may not load in FL's
# Python subinterpreter, and JUCE writes it as one line of plain elements with quoted attributes.
_TRK_RE = re.compile(r"<(Trk_\d+)\b")
_PITCH_RE = re.compile(r"<Pitch_(\d+)\s[^>]*>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')


def _unescape(v):
    return v.replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">") \
        .replace("&amp;", "&")


def element_attrs(xml, element):
    """Attributes (strings) of the first <element ...> in the XML, or None."""
    m = re.search(r"<%s\b[^>]*>" % re.escape(element), xml)
    return {k: _unescape(v) for k, v in _ATTR_RE.findall(m.group(0))} if m else None


def _pitch_tags(xml):
    """(track, index, match) for every Pitch_N element, in document order."""
    tracks = [(m.start(), m.group(1)) for m in _TRK_RE.finditer(xml)]
    for m in _PITCH_RE.finditer(xml):
        trk = None
        for pos, name in tracks:
            if pos < m.start():
                trk = name
        yield trk, int(m.group(1)), m


def project_notes(xml):
    """[{track, index, **attributes as numbers}] of every Pitch_N element (one per note)."""
    return [dict(track=trk, index=idx, **{k: _num(v) for k, v in _ATTR_RE.findall(m.group(0))})
            for trk, idx, m in _pitch_tags(xml)]


def set_note_attrs(xml, edits, track=None):
    """edits = {note index: {attribute: value}} applied to the Pitch_N elements of one track (the
    first one when track is None); everything else stays byte-identical. Returns the new XML."""
    tags = list(_pitch_tags(xml))
    if track is None and tags:
        track = tags[0][0]
    missing = set(edits) - {idx for trk, idx, _m in tags if trk == track}
    if missing:
        raise KeyError(f"no notes {sorted(missing)} in {track}")
    out, last = [], 0
    for trk, idx, m in tags:
        if trk != track or idx not in edits:
            continue
        tag = m.group(0)
        for attr, value in edits[idx].items():
            v = repr(float(value)) if isinstance(value, float) else str(int(value) if isinstance(value, bool) else value)
            if re.search(r'\b%s="' % re.escape(attr), tag):
                tag = re.sub(r'(\b%s=")[^"]*' % re.escape(attr), lambda mm: mm.group(1) + v, tag)
            else:
                tag = tag[:-2] + f' {attr}="{v}"/>' if tag.endswith("/>") else tag[:-1] + f' {attr}="{v}">'
        out += [xml[last:m.start()], tag]
        last = m.end()
    return "".join(out) + xml[last:]


def _num(v):
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def set_xml_attr(xml, element, attr, value):
    """Replace one attribute of the first <element ...> in JUCE's single-line XML, keeping the rest
    byte-identical. JUCE formats doubles with up to 15 significant digits; repr() is accepted."""
    m = re.search(r"<%s\b[^>]*>" % re.escape(element), xml)
    if not m:
        raise KeyError(element)
    tag = m.group(0)
    new = re.sub(r'(\b%s=")[^"]*(")' % re.escape(attr), lambda mm: mm.group(1) + str(value) + mm.group(2), tag)
    if new == tag and f' {attr}="' not in tag:
        new = tag[:-2] + f' {attr}="{value}"/>' if tag.endswith("/>") else tag[:-1] + f' {attr}="{value}">'
    return xml[:m.start()] + new + xml[m.end():]


def fst_plugin_blob(fst):
    """Event 213 payload of an FL .fst file (plugin preset) = the plugin's state blob."""
    o = fst.find(b"FLdt") + 8
    while o < len(fst):
        ev = fst[o]
        o += 1
        if ev < 64:
            o += 1
        elif ev < 128:
            o += 2
        elif ev < 192:
            o += 4
        else:
            n = sh = 0
            while True:
                b = fst[o]
                o += 1
                n |= (b & 0x7F) << sh
                sh += 7
                if b < 128:
                    break
            if ev == 213:
                return fst[o:o + n]
            o += n
    raise ValueError("no event 213 in .fst")


# --- pitch correction (what Newtone's 'correct pitch' does to a note, done in the XML) ----------
NOTE_NAMES = {"c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5, "f#": 6, "gb": 6, "g": 7,
              "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11}
SCALES = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "chromatic": list(range(12)),
          "harmonic minor": [0, 2, 3, 5, 7, 8, 11], "dorian": [0, 2, 3, 5, 7, 9, 10],
          "pentatonic": [0, 2, 4, 7, 9], "minor pentatonic": [0, 3, 5, 7, 10]}


def scale_pitches(scale="chromatic"):
    """'D minor' -> set of pitch classes; 'chromatic' -> all 12."""
    parts = scale.lower().split(None, 1)
    if parts[0] in NOTE_NAMES:
        root, kind = NOTE_NAMES[parts[0]], (parts[1] if len(parts) > 1 else "major")
    else:
        root, kind = 0, scale.lower()
    return {(root + i) % 12 for i in SCALES[kind]}


def snap(pitch, pcs):
    best = None
    for cand in range(int(pitch) - 7, int(pitch) + 8):
        if cand % 12 in pcs and (best is None or abs(cand - pitch) < abs(best - pitch)):
            best = cand
    return best


def correct_xml(xml, scale="chromatic", amount=1.0, variation=None, notes=None):
    """Move each note (Pitch_N) toward the nearest pitch of the scale: fCurPitch = target and
    fCurrentPitchOffset = target - fOrigPitch (the engine renders the offset; fCurPitch is the display).
    amount 0..1 blends; variation (0..1) sets fDrift (0 = flatten vibrato/drift, 1 = keep).
    Silent/unvoiced pseudo-notes (fOrigVelocity 0) are left alone."""
    pcs = scale_pitches(scale)

    def fix(m):
        tag = m.group(0)
        idx = int(m.group(1))
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag))
        if (notes is not None and idx not in notes) or float(attrs.get("fOrigVelocity", 0)) <= 0:
            return tag
        orig = float(attrs["fOrigPitch"])
        target = orig + (snap(orig, pcs) - orig) * amount
        for k, v in (("fCurPitch", repr(target)), ("fCurrentPitchOffset", repr(target - orig))) + \
                ((("fDrift", repr(float(variation))),) if variation is not None else ()):
            tag = re.sub(r'(\b%s=")[^"]*' % k, lambda mm: mm.group(1) + v, tag)
        return tag

    return re.sub(r"<Pitch_(\d+) [^>]*>", fix, xml)


def fst_with_blob(fst, blob):
    """Copy of an FL .fst with its event-213 payload (plugin state) replaced."""
    start = fst.find(b"FLdt")
    o = start + 8
    while o < len(fst):
        ev, p = fst[o], o + 1
        if ev < 64:
            o = p + 1
        elif ev < 128:
            o = p + 2
        elif ev < 192:
            o = p + 4
        else:
            n = sh = 0
            q = p
            while True:
                b = fst[q]
                q += 1
                n |= (b & 0x7F) << sh
                sh += 7
                if b < 128:
                    break
            if ev == 213:
                v, m = b"", len(blob)
                while True:
                    v += bytes([(m & 0x7F) | (0x80 if m > 0x7F else 0)])
                    m >>= 7
                    if not m:
                        break
                body = fst[start + 8:o] + bytes([213]) + v + bytes(blob) + fst[q + n:]
                return fst[:start] + b"FLdt" + struct.pack("<I", len(body)) + body
            o = q + n
    raise ValueError("no event 213 in .fst")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        data = open(path, "rb").read()
        blob = fst_plugin_blob(data) if path.lower().endswith(".fst") else data
        st = NewtoneState(blob)
        ok = st.encode() == blob
        print(path, "bytes", len(blob), "roundtrip", "OK" if ok else "MISMATCH")
        print("  tags", [(t, len(d)) for t, d in st.sections], "editor", st.editor(), "params", st.engine_params())
        print("  sample", repr(st.sample_path), "notes", len(st.notes()))
        print("  xml", (st.xml or "")[:300])
