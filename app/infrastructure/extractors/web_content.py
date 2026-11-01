"""DOM content selection executed by Playwright in the source page."""

EXTRACT_WEB_CONTENT = r"""() => {
    if (!document.body) return '';
    const body = document.body.cloneNode(true);
    const excluded = [
        'nav', 'footer', 'aside', 'form', 'button', 'input', 'select',
        'textarea', 'script', 'style', 'noscript', 'template', 'iframe',
        'svg', 'canvas', '[hidden]', '[aria-hidden="true"]',
        '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
        '[role="dialog"]', '[role="menu"]'
    ].join(',');
    body.querySelectorAll(excluded).forEach(node => node.remove());
    const noise = new RegExp(
        '(?:^|[\\s_-])(?:advertisement|advertising|ads|cookie-banner|' +
        'cookie-consent|newsletter|related-posts|related-articles|' +
        'site-footer|page-footer|global-footer|' +
        'social-share|share-buttons)(?:$|[\\s_-])', 'i'
    );
    body.querySelectorAll('*').forEach(node => {
        const style = node.getAttribute('style') || '';
        if (noise.test(`${node.id} ${node.className}`) ||
            /(?:display\s*:\s*none|visibility\s*:\s*hidden)/i.test(style)) {
            node.remove();
        }
    });
    body.querySelectorAll('header').forEach(node => {
        if (!node.closest('article, main, [role="main"]')) node.remove();
    });
    const score = node => {
        const paragraphs = Array.from(node.querySelectorAll('p'));
        const length = paragraphs.reduce(
            (sum, p) => sum + (p.textContent || '').trim().length, 0
        );
        const links = Array.from(node.querySelectorAll('a')).reduce(
            (sum, link) => sum + (link.textContent || '').length, 0
        );
        return length - links * 2 + paragraphs.length * 80;
    };
    let root = body;
    for (const selector of [
        '[itemprop~="articleBody"]', 'article', 'main, [role="main"]'
    ]) {
        const candidates = Array.from(body.querySelectorAll(selector))
            .filter(node => (node.textContent || '').trim());
        if (candidates.length) {
            root = candidates.reduce((best, node) =>
                score(node) > score(best) ? node : best
            );
            break;
        }
    }
    if (root === body) {
        const candidates = Array.from(body.querySelectorAll('div, section'))
            .filter(node => node.querySelectorAll('p').length >= 2);
        root = candidates.reduce((best, node) =>
            score(node) > score(best) ? node : best, body
        );
    }
    const blocks = new Set([
        'P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'LI', 'UL', 'OL',
        'BLOCKQUOTE', 'PRE', 'DIV', 'SECTION', 'ARTICLE', 'MAIN',
        'FIGCAPTION', 'TABLE', 'TR'
    ]);
    const walk = node => {
        if (node.nodeType === 3) return node.textContent.replace(/\s+/g, ' ');
        if (node.nodeType !== 1) return '';
        if (node.tagName === 'BR') return '\n';
        const text = Array.from(node.childNodes).map(walk).join('');
        if (node.tagName === 'TD' || node.tagName === 'TH') {
            return text + '\t';
        }
        return blocks.has(node.tagName) ? '\n' + text + '\n' : text;
    };
    return walk(root).split('\n')
        .map(line => line.replace(/[^\S\t]+/g, ' ').trim())
        .filter(Boolean).join('\n');
}"""
