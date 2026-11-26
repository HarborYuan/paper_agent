// Company logos for paper cards, matched against the paper's `main_company` (same mapping as the
// v2.0.7 PaperCard). Companies without a logo here get none; the card still shows main_affiliation.
import bytedanceLogo from '../assets/logos/bytedance.svg';
import googleLogo from '../assets/logos/google.svg';
import metaLogo from '../assets/logos/meta.svg';
import alibabaLogo from '../assets/logos/alibaba.svg';
import openaiLogo from '../assets/logos/openai.svg';
import microsoftLogo from '../assets/logos/microsoft.svg';
import deepseekLogo from '../assets/logos/deepseek.svg';
import deepmindLogo from '../assets/logos/deepmind.svg';

const LOGO_MAP = {
    'ByteDance Seed': bytedanceLogo,
    'ByteDance': bytedanceLogo,
    'TikTok': bytedanceLogo,
    'Google DeepMind': deepmindLogo,
    'DeepMind': deepmindLogo,
    'Google': googleLogo,
    'Meta Platforms': metaLogo,
    'Meta Reality Labs': metaLogo,
    'Meta': metaLogo,
    'FAIR': metaLogo,
    'Alibaba': alibabaLogo,
    'DeepSeek': deepseekLogo,
    'OpenAI': openaiLogo,
    'Microsoft': microsoftLogo,
};

// Longest key first, so "Google DeepMind" wins over "Google".
const MATCH_KEYS = Object.keys(LOGO_MAP)
    .sort((a, b) => b.length - a.length)
    .map(key => ({ lower: key.toLowerCase(), original: key }));

export const companyLogo = (company) => {
    if (!company) return null;
    const lower = company.toLowerCase();
    const match = MATCH_KEYS.find(k => lower.includes(k.lower));
    return match ? LOGO_MAP[match.original] : null;
};
