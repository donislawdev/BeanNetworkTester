"""What a captured packet carries, read from its bytes. A leaf: no package imports.

``payload_length`` answers one question for the payload-size scope (``BeanCore``
step 2): how many bytes of transport data are in this packet? It runs on the
capture thread, for every packet of a session that armed the scope, so it reads
plain bytes and allocates nothing.

🔴 It may NOT raise, whatever the bytes are: an exception in ``decide()`` ends the
session. Every index is behind a length test, and ``tests/test_wire.py`` feeds it
arbitrary bytes.

An answer of ``-1`` means "cannot be read", and the caller keeps such a packet out
of scope - what cannot be identified must not be damaged. That covers:

  * anything that is not UDP or TCP directly over IPv4 or IPv6 (ICMP, and IPv6
    behind an extension header, as in ``ice._start``);
  * a FRAGMENT, the first one included: it has a UDP header, but that header gives
    the length of the whole datagram, of which this packet carries a part;
  * a packet cut short, or whose own length fields do not fit in it.

Zero is a real answer: an empty datagram, a bare TCP acknowledgement. That is why
this is not ``ice._start``, which reports an empty payload as nothing to parse.

The sizes are the ones the capture driver hands over. MEASURED 2026-11-10 on
Windows (WinDivert, over a virtual switch and over a physical network): TCP
arrives at segment size in both directions, never merged by send or receive
offload, and a UDP datagram above the MTU arrives as ONE packet both ways, so the
size seen is the size the application sent. On Linux (eBPFDivert) TCP arrives in
offloaded pieces above one segment, and such a datagram as fragments.

A packet can be LONGER than its IP header says: a frame below the link's minimum
is padded, and a capture that sits before the IP layer sees the padding. The IP
length is therefore where a packet ends, when it has one. A segmentation-offload
packet too large for the 16-bit field carries 0 there, and then the buffer ends it.
"""

MIN_PACKET = 28          # the shortest readable one: IPv4 header + UDP header


def payload_length(raw, is_tcp):
    """Bytes of transport data in ``raw``, or -1 when that cannot be read.

    ``is_tcp`` is what the caller already knows about the packet; a packet that is
    neither TCP nor UDP is asked as not-TCP and answers -1.
    """
    size = len(raw)
    if size < MIN_PACKET:
        return -1
    first = raw[0]
    if first >> 4 == 4:
        head = (first & 0x0F) * 4
        # "more fragments" or a fragment offset: a piece of a datagram
        if head < 20 or (raw[6] & 0x3F) or raw[7]:
            return -1
        proto = raw[9]
        declared = (raw[2] << 8) | raw[3]
    elif first >> 4 == 6:
        head = 40
        proto = raw[6]
        declared = (raw[4] << 8) | raw[5]
        if declared:
            declared += 40
    else:
        return -1
    if is_tcp:
        if proto != 6 or size < head + 20:
            return -1
        # Where the packet ends: its IP length, never past the buffer. Without it
        # a bare acknowledgement padded to the link's minimum frame would read as
        # six bytes of data. 0 = no length to go by (see the module docstring).
        end = declared if 0 < declared < size else size
        data = head + (raw[head + 12] >> 4) * 4
        return end - data if head + 20 <= data <= end else -1
    if proto != 17 or size < head + 8:
        return -1
    length = (raw[head + 4] << 8) | raw[head + 5]
    return length - 8 if 8 <= length <= size - head else -1
