# Jochos Don Chente — website redesign

A hand-coded static site for [jochosdonchente.com](https://jochosdonchente.com), replacing the GoDaddy Website Builder page. It has no build step and no dependencies. Deploy this folder as the site root on Netlify, Vercel, Cloudflare Pages or GitHub Pages.

```
don-chente-jochos/
├── index.html          English (canonical, x-default)
├── es/index.html       Spanish, full translation
├── 404.html
├── assets/css/styles.css
├── assets/js/main.js   All behaviour + CONFIG block (hours, form endpoint)
├── assets/img/         Client photos, converted to WebP (640w + 1200w)
├── assets/fonts/       Self-hosted Big Shoulders Display + DM Sans (OFL)
├── sitemap.xml         Includes hreflang alternates
├── robots.txt
└── site.webmanifest
```

Preview locally: `python3 -m http.server` inside this folder, then open http://localhost:8000.

## What was kept from the old site

| Old site | New site |
|---|---|
| Tagline "¿A dónde va la gente? ¡A Jochos Don Chente!" (repeated 10×) | Hero copy + animated ticker |
| "Are you having an event? We cater!" | Full catering section with a quote form |
| Menu (10 items, prices, descriptions) | Filterable menu cards with photos and an Order button on every item |
| Texas Bucket List video | Click-to-play embed that loads nothing until tapped, plus a "As seen on" badge in the hero |
| Photo gallery | Masonry gallery with a lightbox (keyboard arrows supported) |
| "My Blog" / Instagram prompt | Instagram follow CTA in the gallery |
| Facebook / Instagram / TikTok | Footer socials |
| Click-to-call phone | Header, hero, order sheet, sticky mobile bar, footer |
| Bilingual copy | Proper EN + ES pages with hreflang tags |

Dropped: the second video (a GoDaddy stock "Timelapse of a Cold Winter Day" placeholder), the empty blog RSS feeds and the cookie banner. The new site sets no cookies. Add a banner if analytics are added.

## What's new (sales + SEO)

- **Order everywhere.** A sticky mobile action bar (Call / Directions / Order), an order sheet that remembers which dish you tapped, and an order band. Pickup by phone is labeled "Best price" to steer customers away from paying app commissions.
- **Live open/closed status** in the restaurant's time zone (America/Chicago), with today's hours highlighted.
- **Address, hours, map and directions.** None of these were on the old site. The map only loads when tapped, which keeps the page fast.
- **Catering lead form.** It posts to a form service if one is configured. Otherwise it opens the visitor's messaging app with the request pre-filled and addressed to the restaurant.
- **SEO:** Restaurant, Menu (all 10 items with prices), FAQPage and VideoObject structured data; unique EN/ES titles and descriptions; Open Graph share image; sitemap with hreflang; a "What's a jocho?" section and FAQ aimed at real searches; semantic HTML and alt text on every photo.
- **Performance:** self-hosted fonts, WebP images with `srcset`, native lazy loading for images below the fold, no frameworks. Total JS is about 13 KB.
- **Motion is restrained:** no fade-in on scroll and nothing that spins. The ticker only moves with the page scroll, and only the small stripe next to each section label draws in. All motion is off for visitors who ask their system for reduced motion.
- **Accessibility:** skip link, focus styles, native `<dialog>`, reduced-motion support, and a visible label on every form field.
- A Spanish-language browser landing on `/` gets a small "¿Prefieres español?" prompt. It never auto-redirects, because redirects hurt SEO.

## Confirm with the client before launch

1. **Hours.** Online listings disagree. The site currently says **Tue–Fri 2:00–9:30pm, closed Sat–Mon**. Hours live in 4 places: `CONFIG.hours` in `main.js`, the hours table and footer in both HTML files, the JSON-LD `openingHoursSpecification`, and the FAQ answer.
2. **Ordering links.** DoorDash and Postmates were found via search. The **Uber Eats URL was derived** from the Postmates store ID (Uber and Postmates share store IDs) and needs a click-test. Remove any platform they don't use from the order sheet, the order band and the FAQ.
3. **Direct online ordering.** If they have or want Square / Toast / Clover online ordering, uncomment the block at the top of the order sheet in both HTML files. Direct ordering avoids the roughly 15–30% app commission.
4. **Catering form delivery.** Create a free Formspree (or Basin / Getform) form and paste its URL into `CONFIG.formEndpoint` in `assets/js/main.js`. Until then, submissions open a pre-filled text message to (210) 461-2955.
5. **Menu photo matching.** Photos were matched to dishes by eye. Confirm which photo is which, especially Flameado and Campechana.
6. **Google Business Profile.** Make sure the name, address, phone and hours match the site exactly. This matters as much as the site itself for local search.
7. **Reviews / testimonials.** None were added, to avoid inventing quotes. Real Google reviews would be a strong addition.

## Deploy

1. Point the host at this folder (for Netlify: publish directory `don-chente-jochos`).
2. Move the domain's DNS from GoDaddy Website Builder to the new host.
3. Submit `https://jochosdonchente.com/sitemap.xml` in Google Search Console.
