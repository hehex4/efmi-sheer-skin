"""Small original shader fixture with discoverable material and lighting chains."""
from pathlib import Path

FIXED = '''cbuffer cb6 : register(b6) { float4 cb6[7]; };
Texture2D<float4> t0 : register(t0);
SamplerState s0 : register(s0);
void main(
  float4 v0 : SV_Position,
  float2 v1 : TEXCOORD0,
  float3 v2 : TEXCOORD1,
  float3 v3 : TEXCOORD2,
  float4 v4 : TEXCOORD3,
  out float4 o0 : SV_Target0)
{
  float4 r0, r1, r2, r3, r4, r5;
  uint4 bitmask, uiDest;
  r0.xyz = -v2.xyz;
  r0.w = dot(r0.xyz, r0.xyz);
  r0.w = rsqrt(r0.w);
  r1.xyz = r0.xyz * r0.www;
  r4.xyz = normalize(v3.xyz);
  r5.xyz = normalize(v4.xyz);
  r2.xyzw = t0.Sample(s0, v1.xy).xyzw;
  r3.xyz = cb6[6].xyz * r2.xyz;
  o0.xyz = r3.xyz * saturate(dot(r4.xyz, r5.xyz)) + 0.01 * r1.xyz + 0.01 * v4.w;
  o0.w = 1;
  return;
}
'''


def write_fixed(path):
    """Write an original fixture and return builder's explicit mapping arguments."""
    Path(path).write_text(FIXED, encoding='utf-8')
    lines = FIXED.splitlines()
    return ['--normal-input', 'v3', '--tangent-input', 'v4',
            '--aniso-n', 'r4.xyz@' + str(lines.index('  r4.xyz = normalize(v3.xyz);') + 1),
            '--aniso-l', 'r5.xyz@' + str(lines.index('  r5.xyz = normalize(v4.xyz);') + 1)]
