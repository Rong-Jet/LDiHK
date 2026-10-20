/** Must stay in sync with the backend bearer-ID validation. */
export const LDIHK_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$/;

export function isValidLdihkId(value: string): boolean {
  return LDIHK_ID_PATTERN.test(value);
}

const ADJECTIVES = [
  'cosmic', 'quantum', 'aurora', 'cyber', 'neon', 'stellar', 'plasma', 'shadow',
  'solar', 'vortex', 'emerald', 'sapphire', 'obsidian', 'spectral', 'lunar',
  'hyper', 'alpha', 'omega', 'magnetic', 'crypto',
];
const NOUNS = [
  'pegasus', 'nebula', 'hawk', 'leopard', 'viper', 'phoenix', 'cyclone', 'glider',
  'pulsar', 'comet', 'horizon', 'phantom', 'beacon', 'titan', 'matrix', 'falcon',
  'griffin', 'sentinel', 'orion',
];

// RFC 4648 base32 alphabet, lowercase. 32 symbols -> exactly 5 random bits each.
const BASE32_ALPHABET = 'abcdefghijklmnopqrstuvwxyz234567';
export const LDIHK_ID_SUFFIX_LENGTH = 12; // 12 * 5 = 60 random bits

function getCrypto(): Crypto {
  if (typeof globalThis.crypto?.getRandomValues !== 'function') {
    throw new Error('Secure random number generation is not available in this browser.');
  }
  return globalThis.crypto;
}

/** Uniform random integer in [0, max) using rejection sampling (no modulo bias). */
function secureRandomIndex(max: number): number {
  const buffer = new Uint32Array(1);
  const limit = Math.floor(0x100000000 / max) * max;
  let value: number;
  do {
    getCrypto().getRandomValues(buffer);
    value = buffer[0];
  } while (value >= limit);
  return value % max;
}

function secureBase32(length: number): string {
  const bytes = new Uint8Array(length);
  getCrypto().getRandomValues(bytes);
  // 256 is a multiple of 32, so masking the low 5 bits is uniform.
  return Array.from(bytes, (byte) => BASE32_ALPHABET[byte & 31]).join('');
}

/**
 * Friendly but unguessable LDiHK-ID, e.g. `ldihk-cosmic-pegasus-k3j9x2m4q7ab`.
 * The word prefix is cosmetic; the 12-char base32 suffix carries 60 random bits.
 */
export function generateLdihkId(): string {
  const adjective = ADJECTIVES[secureRandomIndex(ADJECTIVES.length)];
  const noun = NOUNS[secureRandomIndex(NOUNS.length)];
  return `ldihk-${adjective}-${noun}-${secureBase32(LDIHK_ID_SUFFIX_LENGTH)}`;
}
