// =====================================================================================================
//  sheer_core.hlsl —— 着色器透肉模板(skill efmi-sheer-skin)
//  The view-dependent fabric coverage follows the vanilla Last Rite sheer material; the caller supplies linear skin and fabric colours.
//  The generator places the parameter block first, then the complete anisotropic core and this callable core before main().
//  Keep the anisotropic core even with zero highlight gain because its debug modes provide the path and scope probes.
//  Register names in the injection example are placeholders; map every value from the current shader before generation.
// =====================================================================================================

// ==================== 可调参数:改这里 → 保存 → 游戏里按 F10 ====================
#define SHEER_ALPHA          0.25   // 透光随视角变化的宽度；越大越容易透，常用 0.15–0.45
#define SHEER_W_MIN          0.0    // 正对镜头的最低织物占比；调高会更实、更暗，常用 0–0.75
#define SHEER_W_MAX          0.9    // 轮廓处的最高织物占比；调高会让边缘更实，常用 0.6–1.0
#define SHEER_GAIN           1.0    // 整体透肉强度；0 为原样，1 为完整效果
#define SHEER_SPEC_GAIN      0.0    // 丝袜高光强度；0 为关闭，常用 0–1.5
#define SHEER_SPEC_COUPLING  1.0    // 高光随透肉减弱的程度；0 不联动，1 完全联动
// ==================== 以上 ====================

// ---- 透肉核心(可调参数只在上面那一段,这里不用动)----
#define SHEER_ALPHA_OFFSET  1.0                              // Vanilla sheer alpha offset; re-derive it if the source material changes.

// 用户开关：丝袜画在身体 draw 上且启用高光时设 1，只让高光落在贴图差异像素；独立丝袜网格保持 0。
#define SHEER_SPEC_STOCKING_ONLY 0

// 用户参数：常数肤色必须填当前角色皮肤 diffuse 的线性中位值，不能直接填 sRGB 数字。
#define SHEER_SKIN_ALBEDO   float3(0.7682, 0.6172, 0.5333)
// A bare-leg or baked skin texture must use a free slot selected from the current Mods installation.
// Texture2D<float4> t90 : register(t90);

// 用户参数：UV 框采用左闭右开；缩小它只为排除同一 draw 内的非丝袜区域。
#define SHEER_BOX_U0 0.0
#define SHEER_BOX_V0 0.0
#define SHEER_BOX_U1 1.0
#define SHEER_BOX_V1 1.0
// Return one inside the selected stocking UV region and zero outside it.
float SheerMask(float2 uv)
{
    return (uv.x >= SHEER_BOX_U0 && uv.x < SHEER_BOX_U1 && uv.y >= SHEER_BOX_V0 && uv.y < SHEER_BOX_V1) ? 1.0 : 0.0;
}

// Blend linear fabric and skin colours with the vanilla view-dependent coverage curve.
float3 LastRiteSheerBase(float3 fabric, float3 skin, float alpha, float3 N, float3 V, out float coverage)
{
    float t   = saturate(alpha + 1.0 - SHEER_ALPHA_OFFSET);
    float ndv = saturate(dot(N, V));
    float f   = min(1.0, pow(1.05 - ndv, 2.0 * t));
    coverage  = lerp(SHEER_W_MIN, SHEER_W_MAX, f);
    return lerp(skin, fabric, coverage);
}

/* ---------------- 注入片段 ----------------
   在 main() 开头的变量声明处加:
       float _shCov = 1.0;    // Fabric coverage; one keeps the original fabric colour.
       float _shScope = 0.0;  // Debug scope weight; optimized out in the normal mode.
       float _shStk = 1.0;    // Stocking pixel mask; keep one for a separate stocking mesh.
   Insert after the tinted diffuse assignment; register names below are placeholders:
  {
    float3 _shOrig = r5.xyz;                                      // Tinted fabric colour in linear space.
    float3 _shSkin = SHEER_SKIN_ALBEDO;                           // Constant skin source selected for this character.
    // Sample a bare-leg texture with the same sampler, UV, bias, and material tint as the original diffuse.
    // float3 _shSkin = cb6[6].xyz * t90.SampleBias(s1_s, v1.xy, cb1[26].x).xyz;
    float  _shW = 1.0;
    float3 _shBase = LastRiteSheerBase(r5.xyz, _shSkin, SHEER_ALPHA, normalize(v3.xyz), <V 寄存器或早捕获的 _anisoV>, _shW);
    float  _shMix = SheerMask(v1.xy) * SHEER_GAIN;
    r5.xyz = lerp(r5.xyz, _shBase, _shMix);
    _shCov = lerp(1.0, _shW, _shMix);
    float3 _shRel = abs(r5.xyz - _shOrig) / max(_shOrig, 0.02);
    _shScope = smoothstep(0.05, 0.15, max(_shRel.x, max(_shRel.y, _shRel.z)));   // Fade debug green from 5% to 15% relative change so BC noise stays dark.
#if SHEER_SPEC_STOCKING_ONLY
    // Derive the stocking mask from fabric-versus-skin difference so tuning coverage cannot suppress highlight scope.
    float3 _shStkD = abs(_shOrig - _shSkin) / max(_shSkin, 0.02);
    _shStk = SheerMask(v1.xy) * smoothstep(0.05, 0.15, max(_shStkD.x, max(_shStkD.y, _shStkD.z)));
#endif
  }

   ---------------- Call point: after final o0 colour and before the shader's remaining output writes ----------------
   Keep the complete block at zero highlight gain so debug modes remain available.
  {
    float3 _shLit = ApplyAnisoHighlight(o0.xyz, _anisoN, _anisoL, _anisoV, v4.xyz, v4.w);
#if ANISO_DEBUG_MODE == 0 || ANISO_DEBUG_MODE == 7
    if (SHEER_SPEC_GAIN > 0.0)          // Constant folding removes the branch at zero and avoids lerp(a, NaN, 0).
      o0.xyz = lerp(o0.xyz, _shLit, SHEER_SPEC_GAIN * lerp(1.0, _shCov, SHEER_SPEC_COUPLING) * _shStk);
#if ANISO_DEBUG_MODE == 7
    o0.xyz = lerp(o0.xyz, float3(0.0, 1.0, 0.0), _shScope);    // Scope probe colours only pixels whose sheer blend made a visible change.
#endif
#else
    o0.xyz = _shLit;                    // Debug modes must bypass coverage mixing to preserve their diagnostic colours.
#endif
  }
*/
