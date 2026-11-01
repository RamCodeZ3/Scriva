"""DOM extraction fixtures run against an explicitly configured Lightpanda."""

import os
import unittest
from unittest.mock import patch

from infrastructure.browser.lightpanda import lightpanda_page
from infrastructure.extractors.web_content import EXTRACT_WEB_CONTENT


@unittest.skipUnless(
    os.environ.get("TEST_LIGHTPANDA_CDP_URL"),
    "Set TEST_LIGHTPANDA_CDP_URL to run DOM integration tests.",
)
class WebContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_content_selection_and_cleanup(self):
        fixtures = [
            (
                "<header>Site menu</header><nav>Navigation</nav>"
                "<article><header><h1>Article title</h1></header>"
                "<p>Useful <span>inline</span> text.</p>"
                "<form>Sign up<input><button>Submit</button></form>"
                "<aside>Recommendations</aside><footer>Share</footer>"
                "</article><footer>Site footer</footer>",
                "Article title\nUseful inline text.",
            ),
            (
                "<main><h1>Outer title</h1><article>"
                '<div itemprop="articleBody"><h2>Section</h2>'
                "<p>Article body.</p></div><p>Author profile</p>"
                "</article></main>",
                "Section\nArticle body.",
            ),
            (
                '<article><p><a href="/">Related</a></p></article>'
                "<article><h1>Actual article</h1><p>Longer useful prose."
                "</p><p>Another paragraph.</p></article>",
                "Actual article\nLonger useful prose.\nAnother paragraph.",
            ),
            (
                '<div role="main"><h4>Details</h4><p>First<br>Second</p>'
                "<ul><li>One <span>item</span></li><li>Two</li></ul>"
                "<blockquote><p>A quote.</p></blockquote>"
                "<table><tr><th>Name</th><th>Value</th></tr>"
                "<tr><td>Alpha</td><td>1</td></tr></table></div>",
                "Details\nFirst\nSecond\nOne item\nTwo\nA quote."
                "\nName\tValue\nAlpha\t1",
            ),
            (
                "<main><p>Visible</p><p hidden>Hidden</p>"
                '<p aria-hidden="true">Hidden too</p>'
                '<div style="display: none"><p>Invisible</p></div>'
                '<div class="newsletter">Subscribe</div>'
                '<div id="related-articles">Read more</div>'
                "<script>window.secret = 1;</script><style>p{}</style>"
                '<div role="dialog">Cookies</div></main>',
                "Visible",
            ),
            (
                "<header>Site</header><div><p>Fallback content.</p>"
                "<p>Repeated.</p><p>Repeated.</p></div><footer>Legal</footer>",
                "Fallback content.\nRepeated.\nRepeated.",
            ),
            ("<nav>Menu</nav><form>Login</form>", ""),
            (
                '<main><p id="dynamic">Before</p></main>'
                '<script>document.getElementById("dynamic").textContent'
                ' = "After JavaScript";</script>',
                "After JavaScript",
            ),
        ]
        endpoint = os.environ["TEST_LIGHTPANDA_CDP_URL"]
        with patch.dict(os.environ, {"LIGHTPANDA_CDP_URL": endpoint}):
            async with lightpanda_page(10_000) as page:
                for html, expected in fixtures:
                    with self.subTest(expected=expected):
                        await page.set_content(html)
                        original = await page.content()
                        text = await page.evaluate(EXTRACT_WEB_CONTENT)
                        self.assertEqual(text, expected)
                        self.assertEqual(await page.content(), original)
