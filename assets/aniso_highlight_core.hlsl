// ============================================================================
// aniso_highlight_core.hlsl — 各向异性镜面高光核心(skill efmi-anisotropic-highlight)
//
// This moving fabric band uses an anisotropic GGX distribution around H = normalize(L + V).
// A narrow core and wider halo stretch along the fibre direction; Fresnel only modulates strength.
//
// Paste the whole core before main(), then call it after lighting and before the final shader return:
//        o0.rgb = ApplyAnisoHighlight(o0.rgb, N, L, V, T, tangentSign);
// Map N, L, V, T, and handedness from the current shader; keep alpha, extra targets, discard, and face branches unchanged.
// ============================================================================

#define ANISO_DEBUG_MODE 0
// 0 正式效果；1 整片纯绿，检查替换是否命中目标 draw
// 2 NdotL 灰度，迎光白背光黑；3 NdotV 灰度，正对白轮廓黑
// 4 切线 RGB，应沿纤维平滑变化；5 NdotH 灰度，应随光源和镜头移动
// 6 橙色夸张亮带，只检查位置和运动；交付前改回 0

// ---- 参数区：一次只调一组；亮带位置错误时先核对 N/L/V/T ----
#define ANISO_CORE_ALPHA_T      0.20   // 核心横向宽度；调小变窄，常用 0.10–0.35
#define ANISO_CORE_ALPHA_B      0.55   // 核心沿纤维长度；调大变长，常用 0.35–0.80
#define ANISO_CORE_GAIN         0.34   // 核心强度；调大更亮，常用 0–1
#define ANISO_CORE_NDOTL_POW    0.65   // 核心受光衰减；调大更集中在迎光面，常用 0.4–1.2
#define ANISO_HALO_ALPHA_T      0.42   // 两侧渐变宽度；每次增减不超过 0.05，常用 0.25–0.65
#define ANISO_HALO_ALPHA_B      0.72   // 两侧渐变沿纤维长度；调大变长，常用 0.45–0.90
#define ANISO_HALO_GAIN         0.22   // 两侧渐变强度；调大更明显，常用 0–0.8
#define ANISO_HALO_NDOTL_POW    0.70   // 渐变受光衰减；调大更集中在迎光面，常用 0.4–1.2
#define ANISO_FRESNEL_POW       1.45   // 视角调制曲线；调大让变化更靠近轮廓，常用 0.8–3
#define ANISO_CORE_WEIGHT_MIN   0.55   // 正对时核心权重下限；调高会整体更亮，常用 0–1
#define ANISO_CORE_WEIGHT_MAX   0.75   // 掠射时核心权重上限；必须不小于下限，常用 0–1
#define ANISO_HALO_WEIGHT_MIN   0.34   // 正对时渐变权重下限；调高会扩大柔光，常用 0–1
#define ANISO_HALO_WEIGHT_MAX   0.44   // 掠射时渐变权重上限；必须不小于下限，常用 0–1
#define ANISO_TRANSMIT_FRONT    0.82   // 正对时底色透光；1 不压暗，常用 0.6–1
#define ANISO_TRANSMIT_GRAZE    0.52   // 轮廓处底色透光；调低让轮廓更暗，常用 0.3–0.9
#define ANISO_LIGHT_TINT        float3(0.40, 0.28, 0.20)   // 高光目标色；调色时保持所需 RGB 比例

// Normalize safely so zero-length debug inputs cannot create NaN values.
float3 AnisoSafeNormalize(float3 v)
{
    return v * rsqrt(max(dot(v, v), 1.0e-8));
}

// Evaluate the Burley-form anisotropic GGX distribution with roughness along T and B.
float AnisoGGX(float TdotH, float BdotH, float NdotH, float alphaT, float alphaB)
{
    const float PI = 3.14159265;
    float denom = TdotH * TdotH / (alphaT * alphaT)
                + BdotH * BdotH / (alphaB * alphaB)
                + NdotH * NdotH;
    return 1.0 / max(1.0e-4, PI * alphaT * alphaB * denom * denom);
}

// Add the moving anisotropic band in the common space shared by N, L, V, and T.
float3 ApplyAnisoHighlight(
    float3 originalColor,      // Final lit RGB from the original pixel shader.
    float3 shadingNormal,      // Final normal after normal mapping and space conversion.
    float3 mainLightDirection, // Main light vector from the branch that computes NdotL.
    float3 viewDirection,      // EFMI view vector is commonly normalized negative TEXCOORD1; verify per shader.
    float3 meshTangent,        // Mesh tangent, orthogonalized against the final normal below.
    float  tangentSign)        // Tangent handedness, commonly TEXCOORD3.w in EFMI; verify per shader.
{
    float3 N = AnisoSafeNormalize(shadingNormal);
    float3 L = AnisoSafeNormalize(mainLightDirection);
    float3 V = AnisoSafeNormalize(viewDirection);

    float3 halfSeed = L + V;
    float  halfLengthSq = dot(halfSeed, halfSeed);
    float3 H = halfSeed * rsqrt(max(halfLengthSq, 1.0e-8));

    float3 T = AnisoSafeNormalize(meshTangent - N * dot(meshTangent, N));
    float3 B = cross(N, T) * (tangentSign < 0.0 ? -1.0 : 1.0);

    float NdotL = saturate(dot(N, L));
    float NdotV = saturate(dot(N, V));
    float NdotH = saturate(dot(N, H));
    float TdotH = dot(T, H);
    float BdotH = dot(B, H);
    float validHalf = saturate(halfLengthSq * 1000.0);   // Suppress the undefined half vector when L and V oppose each other.

#if ANISO_DEBUG_MODE == 1
    return float3(0.0, 1.0, 0.0);
#elif ANISO_DEBUG_MODE == 2
    return NdotL.xxx;
#elif ANISO_DEBUG_MODE == 3
    return NdotV.xxx;
#elif ANISO_DEBUG_MODE == 4
    return T * 0.5 + 0.5;
#elif ANISO_DEBUG_MODE == 5
    return NdotH.xxx;
#endif

    // Build the narrow central band.
    float coreD = AnisoGGX(TdotH, BdotH, NdotH, ANISO_CORE_ALPHA_T, ANISO_CORE_ALPHA_B);
    float coreSheen = saturate(coreD * ANISO_CORE_GAIN) * pow(NdotL, ANISO_CORE_NDOTL_POW) * validHalf;

    // Build a wider, dimmer halo around the same moving half vector.
    float haloD = AnisoGGX(TdotH, BdotH, NdotH, ANISO_HALO_ALPHA_T, ANISO_HALO_ALPHA_B);
    float haloSheen = saturate(haloD * ANISO_HALO_GAIN) * pow(NdotL, ANISO_HALO_NDOTL_POW) * validHalf;

    // Use Fresnel only to modulate strength and transmission, never band position.
    float fresnel = pow(saturate(1.0 - NdotV), ANISO_FRESNEL_POW);
    float coreWeight = saturate(coreSheen * lerp(ANISO_CORE_WEIGHT_MIN, ANISO_CORE_WEIGHT_MAX, fresnel));
    float haloWeight = saturate(haloSheen * lerp(ANISO_HALO_WEIGHT_MIN, ANISO_HALO_WEIGHT_MAX, fresnel));

    // Combine core and halo as a union so the centre is not brightened twice.
    float sheenWeight = coreWeight + (1.0 - coreWeight) * haloWeight;

    float  transmission = lerp(ANISO_TRANSMIT_FRONT, ANISO_TRANSMIT_GRAZE, fresnel);
    float3 nylonBase = max(originalColor, 0.0) * transmission;
    float3 lightTint = max(nylonBase, ANISO_LIGHT_TINT);

#if ANISO_DEBUG_MODE == 6
    return lerp(nylonBase, float3(1.0, 0.55, 0.15), saturate(sheenWeight * 4.0));
#endif

    // Interpolate toward the tint instead of adding white energy that would clip in HDR.
    return lerp(nylonBase, lightTint, sheenWeight);
}
