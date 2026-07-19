# Fixed-window analysis

## Dataset

The analysis uses three real stage04 trials and one WRITE/SCROLL dataset trial: 276 eligible operation windows. Every sparse feature weight is fixed-window `estimated_excess_pages`; zero-weight VMAs are not inserted into similarity vectors. Anonymous identities remain auxiliary and contain no runtime address.

## Family-pair results

Weighted Jaccard medians (p25–p75):

| Pair | FILE-only | ANON-only | FILE+ANON | Pair count |
|---|---:|---:|---:|---:|
| EDIT–EDIT | 0.865 (0.832–0.895) | 0.688 (0.221–0.833) | 0.770 (0.605–0.864) | 28,680 |
| SCROLL–SCROLL | 0.894 (0.873–0.921) | 0.876 (0.252–0.937) | 0.886 (0.588–0.924) | 325 |
| EDIT–SCROLL | 0.627 (0.612–0.641) | 0.189 (0.162–0.544) | 0.444 (0.422–0.597) | 6,240 |
| WRITE–WRITE | 0.864 (0.781–0.879) | 0.864 (0.782–0.913) | 0.866 (0.786–0.892) | 45 |
| EDIT–WRITE | 0.667 (0.645–0.694) | 0.247 (0.217–0.629) | 0.517 (0.497–0.645) | 2,400 |
| SCROLL–WRITE | 0.529 (0.515–0.539) | 0.412 (0.385–0.441) | 0.486 (0.468–0.497) | 260 |

FILE-only cosine medians are 0.996 for EDIT–EDIT, 0.997 for SCROLL–SCROLL, and 0.878 for EDIT–SCROLL. FILE-only top-10 overlap medians are 0.9, 1.0, and 0.9 respectively; top-k alone is therefore less discriminating than weighted values.

## Answers to the requested questions

1. **EDIT is more similar to EDIT.** The FILE weighted-Jaccard median is 0.865 versus 0.627 for EDIT–SCROLL. The interquartile ranges do not overlap in this dataset.
2. **SCROLL is more similar to SCROLL.** The FILE median is 0.894 versus 0.627 for EDIT–SCROLL; the combined median is 0.886 versus 0.444.
3. **EDIT and SCROLL show useful separation, but this is not a classifier claim.** Weighted distributions separate strongly here; sample balance is very uneven (28,680 EDIT pairs versus 325 SCROLL pairs), and window pairs from the same document/session are correlated.
4. **FILE-only is the most stable representation.** It gives narrow same-family distributions and high cosine repeatability. It also has relatively high cross-family similarity, so absolute similarity alone is not a decision boundary.
5. **Anonymous features provide conditional gain.** For EDIT–SCROLL, adding ANON lowers the weighted median from 0.627 to 0.444 while preserving high within-SCROLL similarity (0.886). However ANON-only EDIT and SCROLL distributions are broad, and combined cosine is less stable than FILE-only. ANON should remain auxiliary.
6. **Process-role noise is not yet isolated by an ablation.** Process role is part of both file and anonymous keys. Current results include that structure; a role-collapsed rerun is required before attributing changes specifically to process roles.

## Aggregate relation statistics

- Same-segment FILE weighted Jaccard: mean 0.858, median 0.865, p25 0.833, p75 0.895, n=28,881.
- Same-operation FILE weighted Jaccard: mean 0.660, median 0.647, p25 0.632, p75 0.660, n=1,549.
- Different-operation FILE weighted Jaccard: mean 0.632, median 0.630, p25 0.610, p75 0.650, n=7,520.
- Same-segment combined weighted Jaccard: median 0.771; different-operation combined median 0.489.

## Interpretation limits

- Referenced is an observation-window residency/access indicator, not an access count and not an exact page-set difference.
- Four chunk windows form one logical edit block; execution sums are window-sample sums, not unique pages.
- Window pairs are not statistically independent because many share a document, process lifetime, and baseline group.
- Class balance and trial count are insufficient for a trained recognizer or calibrated threshold.
- File VMA identity remains `FILE_VMA_OFFSET_INTERVAL`; no 256 KiB page precision is claimed.

Accordingly, `ready_for_operation_recognition=false` and `ready_for_apply=false` remain fixed.
