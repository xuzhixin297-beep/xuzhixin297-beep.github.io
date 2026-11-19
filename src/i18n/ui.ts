
export type Locale = 'en' | 'zh-CN';

const ui = {
    en: {
        home: 'Home',

        physics: 'Physics',
        physicsOverview: 'Overview',
        physicsForum: 'Forum',
        physicsTopics: 'Interesting topics',
        physicsSimulations: 'Experiments & simulations',
        physicsGames: 'Fun games',

        mathematics: 'Mathematics',
        mathematicsOverview: 'Overview',
        mathematicsForum: 'Forum',
        mathematicsTopics: 'Interesting topics',
        mathematicsGames: 'Fun games',

        philosophy: 'Philosophy',
        philosophyOverview: 'Overview',
        philosophyForum: 'Forum',
        epistemology: 'Epistemology',
        religion: 'Religion',
        philosophyGames: 'Fun games',

        journal: 'Journal',
        journalOverview: 'Overview',
        essays: 'Essays',
        questions: 'Questions',
        reflections: 'Reflections',

        settings: 'Settings',

        footer: 'Built with curiosity. Powered by learning.',
    },

    'zh-CN': {
        home: '首页',

        physics: '物理学',
        physicsOverview: '概览',
        physicsForum: '讨论区',
        physicsTopics: '有趣的话题',
        physicsSimulations: '实验与模拟',
        physicsGames: '趣味游戏',

        mathematics: '数学',
        mathematicsOverview: '概览',
        mathematicsForum: '讨论区',
        mathematicsTopics: '有趣的话题',
        mathematicsGames: '趣味游戏',

        philosophy: '哲学',
        philosophyOverview: '概览',
        philosophyForum: '讨论区',
        epistemology: '认识论',
        religion: '宗教',
        philosophyGames: '趣味游戏',

        journal: '日志',
        journalOverview: '概览',
        essays: '文章',
        questions: '问题',
        reflections: '思考',

        settings: '设置',

        footer: '以好奇心为起点，以学习为动力。',
    },
} as const;

export function getLocale(pathname: string): Locale {
    return pathname.startsWith('/zh-cn/') || pathname === '/zh-cn'
        ? 'zh-CN'
        : 'en';
}

export function getUiText(locale: Locale) {
    return ui[locale];
}


export function getLocalizedPathname(
    pathname: string,
    targetLocale: Locale
): string {
    // Remove the Chinese prefix, if it is already present.
    const englishPath = pathname.replace(/^\/zh-cn(?=\/|$)/, '') || '/';

    // English pages use the original path.
    if (targetLocale === 'en') {
        return englishPath;
    }

    // Chinese pages use the /zh-cn/ prefix.
    return englishPath === '/'
        ? '/zh-cn/'
        : `/zh-cn${englishPath}`;
}
