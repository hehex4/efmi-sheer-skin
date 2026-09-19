"""Decode colour textures once, then interpolate in linear light."""
from pathlib import Path
import struct

import numpy as np
from PIL import Image

SRGB_DXGI = {29, 72, 75, 78, 91, 93, 99}
LINEAR_DXGI = {28, 71, 74, 77, 80, 83, 87, 88, 98}


def srgb_to_linear(rgb):
    """Decode sRGB without changing the caller's array."""
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def linear_to_srgb(rgb):
    """Encode bounded output colour; apply only at storage or display time."""
    rgb = np.clip(np.asarray(rgb, dtype=np.float64), 0, 1)
    return np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - .055)


def load_colour_texture(path, colour_space='auto'):
    """Return native-resolution linear RGB and explicit decoding metadata."""
    path = Path(path)
    if colour_space not in ('auto', 'srgb', 'linear'):
        raise ValueError('COLOUR_SPACE_INVALID: use auto, srgb, or linear')
    with path.open('rb') as stream:
        header = stream.read(148)
    fmt, inferred = path.suffix.lstrip('.').upper(), None
    if header[:4] == b'DDS ':
        if len(header) >= 148 and header[84:88] == b'DX10':
            dxgi = struct.unpack_from('<I', header, 128)[0]
            fmt = f'DXGI_{dxgi}'
            if dxgi in SRGB_DXGI:
                inferred = 'srgb'
            elif dxgi in LINEAR_DXGI:
                inferred = 'linear'
            else:
                raise ValueError(f'COLOUR_FORMAT_UNSUPPORTED: {path} DXGI {dxgi}; export a verified RGB8 colour copy with its colour space and retain the source')
        else:
            fmt = 'DDS_LEGACY'
    elif fmt in ('PNG', 'JPG', 'JPEG', 'BMP', 'TGA', 'WEBP'):
        inferred = 'srgb'
    chosen = inferred if colour_space == 'auto' else colour_space
    if chosen is None:
        raise ValueError(f'COLOUR_SPACE_REQUIRED: {path} has no explicit colour-space tag; inspect the runtime SRV format, then pass --colour-space srgb or linear')
    with Image.open(path) as image:
        image.load()
        if image.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            raise ValueError(f'COLOUR_PRECISION_UNSUPPORTED: {path} mode {image.mode}; export a verified RGB8 colour copy before baking')
        if fmt == 'PNG' and len(header) > 24 and header[24] > 8:
            raise ValueError(f'COLOUR_PRECISION_UNSUPPORTED: {path} exceeds 8 bits; export a verified RGB8 colour copy before baking')
        rgb = np.asarray(image.convert('RGB'), dtype=np.float64) / 255
        size = list(image.size)
    linear = srgb_to_linear(rgb) if chosen == 'srgb' else rgb
    return linear, dict(native_size=size, format=fmt, colour_space=chosen,
                        colour_space_override=colour_space, interpolation_space='linear')
