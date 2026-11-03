# Test fixtures

Trimmed copies of real responses saved on 2026-11-04, so the tests run without the network.

- `html/`: MyAnimeList pages. Only the parts the parser reads are kept (ranking rows, the
  sidebar fields, three review blocks). `reviews_5114_p2.html` is page 1's third block without the
  "More Reviews" link, to stand in for a last page; `topanime_empty.html` stands in for the page after
  the end of the ranking.
- `jikan_edge/`: Jikan-Edge API answers for the same titles, cut to three items.

Reviews are anonymised: usernames are `sample_user_N`, review IDs are `9000NN`, avatars are MAL's
default picture and the review text is placeholder text that keeps MyAnimeList's markup (including
the "..." Read more toggle). Anime facts (titles, studios, scores) are left as they were.

When MyAnimeList changes its pages, save a fresh page, trim it the same way and update the expected
values in the tests.
