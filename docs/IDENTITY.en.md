# Movie identity repair

[English](IDENTITY.en.md) | [中文](IDENTITY.md)

The Movie identification page reuses the saved Emby address and API key. Version one supports movie STRMs inside the configured output root, visible to both admin and Emby. It needs no extra plugin, service or TMDB key.

## Workflow

1. Refresh the list. Unidentified means no TMDB/IMDb/TVDB identity. Missing posters/overviews have a separate filter because they can also reflect provider/network failures.
2. Click Search movie and posters. A dialog opens; unambiguous extracted names are searched automatically. Review conflicting years or IDs manually. Search by the file title, parent title or a precise TMDB ID. All movies also includes existing wrong matches.
3. Compare candidate title, year, poster and overview where provided. Sorting does not establish correctness. A missing overview is labelled unavailable. Poster failures show an explanation and retry; expired candidates require another search.
4. Explicitly confirm the intended candidate. Choose whether to replace existing images; the default preserves them. Emby performs its native identification/metadata refresh.
5. Inspect the processing record. Submission and field verification are separate. A timeout does not become successful merely because the old item already had a matching identity. Requested replacement of an existing poster is checked using its image tag; unchanged tags remain unverified, including cases where re-downloading the same image legitimately preserves the tag.

Closing the candidate dialog does not undo an already submitted operation. Refresh records to resume verification after reopening the page.

## Persistence and recovery

- No STRM or cloud video is renamed, moved or deleted. Searches do not enumerate cloud directories or fetch video bytes.
- Private data/identity/identity.sqlite3 stores server identity, STRM path/target fingerprint, confirmed candidate, prior identity and operation state. Back it up privately with other runtime data.
- Service restart preserves records. A library rebuild that changes only Emby item IDs can reuse a matching path/content binding: search the saved ID and explicitly confirm again. Server, path or content changes never silently reuse a binding.
- This version has no unattended batch acceptance, automatic renaming, NFO generation or TV season/episode remapping.
- The service does not directly edit Emby's database or user playback data. Emby's provider-based version/watch associations can change when reidentifying; validate them with your library.

## Consistency and API

Opaque candidate tokens expire after 30 minutes and bind to the server, item, existing identity and STRM content. The browser cannot submit an arbitrary provider result. Duplicate confirmation returns the same operation; another pending candidate for the same movie is blocked. Applying uses the same kernel lock as scan writes.

Confirmation is persisted before contacting Emby. Ambiguous responses are checked, not blindly replayed. Candidate posters are proxied through Emby using a private token, without exposing the API key or upstream image URL. Authenticated requests do not follow HTTP redirects.

The authenticated /api/admin/xstrm/identity/ endpoints include GET items?scope=unmatched|incomplete|all, history, operation?id=..., image?id=...; POST search and apply. Write requests require the existing verification header. Schema upgrades preserve prior records.

References: [Emby Identify](https://emby.media/support/articles/Identify.html), [candidate search](https://dev.emby.media/reference/RestAPI/ItemLookupService/postItemsRemotesearchMovie.html), [apply identification](https://dev.emby.media/reference/RestAPI/ItemLookupService/postItemsRemotesearchApplyById.html).
