# vague-b7-v3: the corrections of Andre's review, as track A took them

`vague-b7-v3.jsonl` is `vague-b7-v2.jsonl` with 13 of its 90 rows changed. All 13 rows were
proposed by Andre's review of 2026-11-26 (branch `andre/vague-prompts-v3`, commit `5a7c2a2`).
Track A checked each row against the rules, and against the issue, the real fix, the hidden tests
and the screen reads of its task. 12 rows are taken as proposed. One row (playwright 43172, L1)
is taken with a further change. No proposed row was left out. The other 77 rows are byte-equal
to version 2.

The review also proposed four sentences for the rules. All four are in
`vague-rules-v3.md`, with changes of wording:

1. L2 must not leave out a behaviour that a hidden test checks on its own. Added: only when the
   issue states that behaviour. A behaviour that only the tests show stays out.
2. Every fact of L1 comes from the issue. Taken as proposed.
3. A place in the code is a name too; a stack trace retold in words is removed. Added: a cause
   that the issue gives can stay when it tells what goes wrong, not where.
4. A name split into words is still that name, and so is the repo's error text in other words.
   Added: a general term of the domain (cookie, clock, JSON) stays, and a message that the fix
   must show follows the "Done when" rule.

## The changed rows

### microsoft__playwright-41942 L2

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. "An unsupported platform error" is a near copy of the repo's own error text "Unsupported platform: android", and a text search for it finds the gold files (both screen reads say so). The new text keeps the symptom in the user's words. Rules: v2 L1 bullet on exact error strings; v3 sentence on a name split into words. Not changed: the L1 of this task still has "unsupported platform" and "unsupported-platform check" (see the end of this file).

Old:

> Playwright now crashes on Termux with an unsupported platform error even when I set the browsers location environment variable. Please make that override work again, like in 1.58.

New:

> Playwright now crashes on Termux, saying the platform is not supported, even when I set the browsers location environment variable. Please make that override work again, like in 1.58.

### microsoft__playwright-42204 L2

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The issue asks that "a complete clone should still be a complete clone", and all its suggested fixes keep the diff; the workaround that turns the diff off is called a workaround. The v2 text ("Collecting report metadata must not change the repository") also allows a fix that stops the fetch or the diff for complete clones. The hidden test "should fetch missing pull request base commit" expects the diff to hold the missing base commit. The new text states what the issue asks and nothing that only the tests show. 28 words.

Old:

> On CI pull request builds, Playwright's git diff capture for the report turns my full clone into a shallow one. Collecting report metadata must not change the repository.

New:

> On CI pull request builds, Playwright's git diff capture turns my full clone into a shallow one. It should still capture the diff but leave the clone complete.

### microsoft__playwright-42792 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. "Each call should add to the locks that the group already has." is not in the issue. The issue asks for one call with one lock name. The hidden test makes two calls and needs them to add up, and one of the three screen reads called the task unfair for this reason. A fact that only the tests show must not enter a prompt (v3 sentence: every fact of L1 comes from the issue). The Done-when line stays: the call accepts a new option that the user names.

Old:

> Playwright Test 1.63 added named locks: tests that hold the same lock do not run at the same time. Today a lock can be declared only in the details of a single test or of a titled test group. There is no way to declare a lock for the suite that is currently loading, from inside the file or group itself. Playwright Test already has a call that configures the enclosing file or group while tests are collected; it sets the execution mode, the retry count and the timeout. Please let that same call also accept a lock, given the same way as in test details, so that all tests in that file or group, including nested groups, take it. Each call should add to the locks that the group already has. This must work together with a fixture override that is scoped to a group, so the lock covers only that group. Motivation: our tests choose a seed through a fixture override. Some seeds use a shared live third-party account, and those tests must not run at the same time. We wrap the fixture override so that a seed that needs the shared account also takes the lock. Today the only way is to reach into private internals of the suite that is loading. Shared or exclusive lock modes and typed lock names are out of scope.
>
> Done when: the call that configures the enclosing group accepts a lock option, as one lock name or a list of names.

New:

> Playwright Test 1.63 added named locks: tests that hold the same lock do not run at the same time. Today a lock can be declared only in the details of a single test or of a titled test group. There is no way to declare a lock for the suite that is currently loading, from inside the file or group itself. Playwright Test already has a call that configures the enclosing file or group while tests are collected; it sets the execution mode, the retry count and the timeout. Please let that same call also accept a lock, given the same way as in test details, so that all tests in that file or group, including nested groups, take it. This must work together with a fixture override that is scoped to a group, so the lock covers only that group. Motivation: our tests choose a seed through a fixture override. Some seeds use a shared live third-party account, and those tests must not run at the same time. We wrap the fixture override so that a seed that needs the shared account also takes the lock. Today the only way is to reach into private internals of the suite that is loading. Shared or exclusive lock modes and typed lock names are out of scope.
>
> Done when: the call that configures the enclosing group accepts a lock option, as one lock name or a list of names.

### microsoft__playwright-42838 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The v2 text has the calls of the issue's code as code: "new Date()", "Temporal.Now.instant()", the four other methods with parentheses, "timeZoneId()" and "Intl.DateTimeFormat". These are names of the web platform, not of the repo, so the review's reason (a name of the code) is only partly right. But the rules remove code snippets, and "DateTimeFormat" is a direct text-search hit on the fixed file (it occurs in packages/injected/src/clock.ts and in one other file at the base commit). The new text says the same things in words. "Temporal.Now" stays: the user must name it, and L2 names it too.

Old:

> Playwright's clock control does not affect the Temporal API in the page. After a test fixes the page time to 1 January 2020 00:00 UTC and opens a blank page, new Date() reports that time, but Temporal.Now.instant() still returns the real current time. This happens in Chromium, Firefox and WebKit, which all ship Temporal natively. Expected: once Playwright controls time (by installing the fake clock, setting a fixed time or setting the system time), Temporal.Now always reports the same instant as Date. This covers every method of Temporal.Now that reads the clock: instant(), zonedDateTimeISO(), plainDateTimeISO(), plainDateISO() and plainTimeISO(). The time zone lookup timeZoneId() and the rest of the Temporal namespace stay untouched, so a method called without a time zone still uses the page's time zone. The fake clock already replaces Date, the timers, performance and Intl.DateTimeFormat, but not Temporal. Temporal.Now is the only part of Temporal that reads the clock. The fake timers library that Playwright's clock is derived from recently added the same support, in the same shape as its existing Intl replacement. Without this, code that moves from Date to Temporal silently runs against real time in tests. A Temporal polyfill hides the problem because it reads the current time from Date. Seen on Playwright 1.63.0.

New:

> Playwright's clock control does not affect the Temporal API in the page. After a test fixes the page time to 1 January 2020 00:00 UTC and opens a blank page, a new Date reports that time, but the current instant from Temporal.Now still returns the real current time. This happens in Chromium, Firefox and WebKit, which all ship Temporal natively. Expected: once Playwright controls time (by installing the fake clock, setting a fixed time or setting the system time), Temporal.Now always reports the same instant as Date. This covers every method of Temporal.Now that reads the clock: the current instant, and the current zoned date-time, plain date-time, plain date and plain time. The time zone lookup and the rest of the Temporal namespace stay untouched, so a method called without a time zone still uses the page's time zone. The fake clock already replaces Date, the timers, performance and date formatting, but not Temporal. Temporal.Now is the only part of Temporal that reads the clock. The fake timers library that Playwright's clock is derived from recently added the same support, in the same shape as its existing Intl replacement. Without this, code that moves from Date to Temporal silently runs against real time in tests. A Temporal polyfill hides the problem because it reads the current time from Date. Seen on Playwright 1.63.0.

### microsoft__playwright-42864 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The issue says "an isolated content script"; it never says "isolated world" or "main world", and it does not say "as other actions do". "main world" is the repo's own term (the type of the execution context, 'main' or 'utility', and the comments of the fix). The new text keeps the reporter's guess in the reporter's words.

Old:

> Since Playwright 1.63 (a regression), highlighting a locator does nothing when the locator uses a custom selector engine that reads global variables of the page. Clicking the same locator works. Reproduction: in a worker-scoped automatic fixture, register a custom selector engine named 'tag' whose lookup functions return matching elements only when a flag variable on the window object is set, and nothing otherwise. The engine is registered without the option that runs it as an isolated content script. In a test, set that flag on the window from the page, set the page content to one button, create a locator with that engine for the button, and highlight it: nothing is highlighted. Clicking the locator then works. During the highlight the engine sees the flag as undefined, but during the click it sees it set. The reporter guesses that highlighting runs the selector in the isolated world, although the engine was not registered for it, and expects it to run in the page's main world as other actions do. Real use case: a selector engine for UI5 apps that reads the UI5 API from a global object on the window; highlighting fails because that global is not defined. Expected: both highlighting and clicking work. Seen on 1.63.0, Windows 11.

New:

> Since Playwright 1.63 (a regression), highlighting a locator does nothing when the locator uses a custom selector engine that reads global variables of the page. Clicking the same locator works. Reproduction: in a worker-scoped automatic fixture, register a custom selector engine named 'tag' whose lookup functions return matching elements only when a flag variable on the window object is set, and nothing otherwise. The engine is registered without the option that runs it as an isolated content script. In a test, set that flag on the window from the page, set the page content to one button, create a locator with that engine for the button, and highlight it: nothing is highlighted. Clicking the locator then works. During the highlight the engine sees the flag as undefined, but during the click it sees it set. The reporter guesses that highlighting runs the selector in an isolated content script, although the engine was not registered for that. Real use case: a selector engine for UI5 apps that reads the UI5 API from a global object on the window; highlighting fails because that global is not defined. Expected: both highlighting and clicking work. Seen on 1.63.0, Windows 11.

### microsoft__playwright-43071 L2

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The issue says that the user name and password must be moved into the proxy fields "(decoded)". The hidden test sends the password se%40cret and expects se@cret at the proxy. The v2 text "Please make it use them" leaves out a behaviour that the issue states and that a test checks on its own (v3 sentence on L2). "percent-decoded" is a general web term. 25 words.

Old:

> Playwright MCP ignores the user name and password written in the proxy URL given on the command line, so authenticated proxies fail. Please make it use them.

New:

> Playwright MCP ignores the user name and password written in the proxy URL given on the command line, so authenticated proxies fail. Use them, percent-decoded.

### microsoft__playwright-43146 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The v2 text says "not an optional minus sign followed only by digits (for example "10abc", or an empty value)". The minus sign is the wording of the real fix's comment and regular expression, and the empty value is test data. The issue says "a Max-Age whose value is not all digits" with the example 10abc. The new text uses the issue's own words. Note for the record: a fix that takes "all digits" literally would also ignore Max-Age=-1, and the first hidden test needs -1 to expire the cookie. The screen called the task fair because the issue points to RFC 6265 section 5.2.2, which allows the minus sign, and the L1 keeps that pointer.

Old:

> Playwright's API request context stores a cookie as already expired when its Set-Cookie header has Max-Age first and then an Expires date in the past. Example: a server sets a session id cookie with Max-Age of one hour, followed by Expires set to 1 January 1970 and path /. A later request does not send the cookie, so a server that echoes the cookie header gets an empty value. With the same two attributes in the other order, the cookie is kept. Expected: Max-Age takes precedence over Expires whatever the order of the attributes (RFC 6265 section 5.3), as in Chromium, Firefox and WebKit, so the cookie lives one hour and is sent. Servers often send a past Expires next to Max-Age for old clients. Cause: the attributes are read in order and both set the same expiry, so the last one wins. A related problem: a Max-Age value that is not an optional minus sign followed only by digits (for example "10abc", or an empty value) is still read as a number; RFC 6265 section 5.2.2 says to ignore such an attribute. Seen on the main branch toward 1.64 and in 1.63; not platform-specific.

New:

> Playwright's API request context stores a cookie as already expired when its Set-Cookie header has Max-Age first and then an Expires date in the past. Example: a server sets a session id cookie with Max-Age of one hour, followed by Expires set to 1 January 1970 and path /. A later request does not send the cookie, so a server that echoes the cookie header gets an empty value. With the same two attributes in the other order, the cookie is kept. Expected: Max-Age takes precedence over Expires whatever the order of the attributes (RFC 6265 section 5.3), as in Chromium, Firefox and WebKit, so the cookie lives one hour and is sent. Servers often send a past Expires next to Max-Age for old clients. Cause: the attributes are read in order and both set the same expiry, so the last one wins. A related problem: a Max-Age value that is not all digits, for example "10abc", is still read as a number; RFC 6265 section 5.2.2 says to ignore such an attribute. Seen on the main branch toward 1.64 and in 1.63; not platform-specific.

### microsoft__playwright-43172 L1

**Taken with a change.** Proposed by Andre's review of 2026-11-26. "The locator parser" is the issue's title, but it is also the fixed file locatorParser.ts split into words (v3 sentence on a name split into words). The review replaced only the first sentence. Two more edits: the next sentence began "The parser turns ...", which named the same thing again and referred to a parser that the text no longer introduces; and "throws an error that says the locator method is unsupported" is a near copy of the repo's error text "Unsupported locator method", which occurs only in the fixed file. The same reason made the review change 41942 L2. The request does not change: both lookups still fail with an error, and the expected selectors and the four languages stay.

Old:

> On Playwright main (1.65 development build), the locator parser does not support two locator methods that were added in 1.64: the method that scopes one locator to be inside another locator, and the page method that finds an element by its reference id from the page snapshot. The parser turns locator text, for example text pasted into the locator box of the trace viewer or the inspector, into a selector. Parsing a JavaScript locator for the third cell scoped inside a row locator throws an error that says the locator method is unsupported. Parsing a lookup by the reference id e5 throws the same error. So pasting the example from the documentation of the scoping method into the locator box does not resolve. Expected: the scoping call parses to the same selector that the client library produces for it (the outer locator, then a chained part with the inner locator), and the reference lookup parses to the same selector that the client produces for that call. This must work in all four languages (JavaScript, Python, Java and .NET), with each language's naming style for the two methods. Found by code review; not specific to an OS or browser.

New:

> On Playwright main (1.65 development build), turning locator code back into a selector fails for two locator methods that were added in 1.64: the method that scopes one locator to be inside another locator, and the page method that finds an element by its reference id from the page snapshot. Playwright does this for locator text, for example text pasted into the locator box of the trace viewer or the inspector. Parsing a JavaScript locator for the third cell scoped inside a row locator throws an error. Parsing a lookup by the reference id e5 throws the same error. So pasting the example from the documentation of the scoping method into the locator box does not resolve. Expected: the scoping call parses to the same selector that the client library produces for it (the outer locator, then a chained part with the inner locator), and the reference lookup parses to the same selector that the client produces for that call. This must work in all four languages (JavaScript, Python, Java and .NET), with each language's naming style for the two methods. Found by code review; not specific to an OS or browser.

### pandas-dev__pandas-68090 L2

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The issue's main statement is that the group-by attribute pairs the group labels with the wrong row positions, and that fetching a group fails as a consequence. One hidden test checks that mapping itself. The v2 text names only the fetch, so a fix of the fetch alone fits it and fails that test. The new text names the wrong pairing in plain words, with no attribute name. 29 words.

Old:

> Grouping by several keys including a categorical one, without sorting and keeping unobserved categories, makes fetching a single group return another group's rows. Please fix it.

New:

> Grouping by several keys including a categorical one, without sorting and keeping unobserved categories, pairs group labels with the wrong rows, so fetching a group returns another group's rows.

### pandas-dev__pandas-69924 L2

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. The issue lists two symptoms: missing datetimes are treated as a large negative number, and "Nanosecond precision is lost", with its own example. A hidden test checks the precision on its own. The v2 text says only "wrong results". The new text names both symptoms of the issue. 27 words.

Old:

> Group-by cumulative sum, min, max and rank give wrong results on datetime or timedelta columns when a group key is NaN. Please fix.

New:

> Group-by cumulative sum, min, max and rank on datetime or timedelta columns mishandle missing values and lose nanosecond precision when a group key is NaN. Please fix.

### pandas-dev__pandas-70205 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. "The error comes from the step after parsing, where the Excel reader puts the names of the header rows onto the columns of the result." retells the issue's stack trace (the call that sets the column names in the Excel reader's sheet parser). The rules remove stack traces (v3 sentence on a place in the code). The symptom, the error message in words and the expected result stay.

Old:

> In pandas 3.0.3, reading an Excel workbook with a two-row column header and the first column as the index fails, while reading the same data from a CSV file with the same options works. The reporter has the same small table as a CSV file and as an xlsx workbook. Reading the CSV with the first two rows as a multi-level column header and the first column as the index returns an empty DataFrame, with no columns and no rows. Reading the workbook with the same options and the openpyxl engine raises a value error that says one name was expected but two were given, for sheet 0. The error comes from the step after parsing, where the Excel reader puts the names of the header rows onto the columns of the result. Expected: no error, and the Excel read gives the same result as the CSV read.

New:

> In pandas 3.0.3, reading an Excel workbook with a two-row column header and the first column as the index fails, while reading the same data from a CSV file with the same options works. The reporter has the same small table as a CSV file and as an xlsx workbook. Reading the CSV with the first two rows as a multi-level column header and the first column as the index returns an empty DataFrame, with no columns and no rows. Reading the workbook with the same options and the openpyxl engine raises a value error that says one name was expected but two were given, for sheet 0. Expected: no error, and the Excel read gives the same result as the CSV read.

### pandas-dev__pandas-70966 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. "in the shared code of this method for Series and DataFrame" points at the base class file that has the fault. The issue gives that place as a link and a class name, which L1 removes. The cause in terms of behaviour (the bounds are put in order by the plain minimum and maximum, so by string order) is in the issue and stays.

Old:

> In pandas, limiting the values of a Series of ordered categorical data to a range, with both a lower and an upper bound, gives the wrong result. Example: a categorical Series with the values zero, one, two, three, four, five, six, with its categories reordered to zero < one < two < three < four < five < six and marked as ordered. Limiting with only a lower bound of two, or only an upper bound of four, gives the expected output. Limiting with lower bound two and upper bound four gives four, four, four, two, two, two, two instead of the expected two, two, two, three, four, four, four, with the same ordered categorical dtype. Swapping the two bounds does not change the result. The likely cause is in the shared code of this method for Series and DataFrame: when both bounds are scalars, it puts them in order with the plain minimum and maximum of the two values, which here is alphabetical string order, not the order of the categories.

New:

> In pandas, limiting the values of a Series of ordered categorical data to a range, with both a lower and an upper bound, gives the wrong result. Example: a categorical Series with the values zero, one, two, three, four, five, six, with its categories reordered to zero < one < two < three < four < five < six and marked as ordered. Limiting with only a lower bound of two, or only an upper bound of four, gives the expected output. Limiting with lower bound two and upper bound four gives four, four, four, two, two, two, two instead of the expected two, two, two, three, four, four, four, with the same ordered categorical dtype. Swapping the two bounds does not change the result. The likely cause: when both bounds are scalars, the method puts them in order with the plain minimum and maximum of the two values, which here is alphabetical string order, not the order of the categories.

### pandas-dev__pandas-71129 L1

**Taken as proposed.** Proposed by Andre's review of 2026-11-26. "in the check that compares the stored categories with the new ones" retells the stack trace (the metadata check of the HDF5 writer and the array comparison under it). The symptom (a value error about a buffer type mismatch from compiled code) and the expected error stay.

Old:

> In pandas 3.1.0rc0 and on the main branch, appending a DataFrame with a categorical column to an HDF5 store in table format fails with the wrong error when the stored data has integer categories and the new data has float categories. Steps: make a DataFrame with one categorical column of the integers 1, 2, 3, 1 (categories 1, 2, 3), and a second one with the same column as the floats 1.0, 2.0, 4.0, 1.0 (categories 1.0, 2.0, 4.0). Open a new HDF5 store, append the first frame in table format under a key, then append the second frame under the same key. In pandas 3.0.6 the second append is rejected with the intended value error, which says that the new categories differ from the stored ones, so the data cannot be appended. Now it fails inside compiled code instead, in the check that compares the stored categories with the new ones, with a value error about a buffer type mismatch (expected double, got long). Expected: the second append raises the same different-categories error as in 3.0.6.

New:

> In pandas 3.1.0rc0 and on the main branch, appending a DataFrame with a categorical column to an HDF5 store in table format fails with the wrong error when the stored data has integer categories and the new data has float categories. Steps: make a DataFrame with one categorical column of the integers 1, 2, 3, 1 (categories 1, 2, 3), and a second one with the same column as the floats 1.0, 2.0, 4.0, 1.0 (categories 1.0, 2.0, 4.0). Open a new HDF5 store, append the first frame in table format under a key, then append the second frame under the same key. In pandas 3.0.6 the second append is rejected with the intended value error, which says that the new categories differ from the stored ones, so the data cannot be appended. Now it fails inside compiled code instead, with a value error about a buffer type mismatch (expected double, got long). Expected: the second append raises the same different-categories error as in 3.0.6.

## Proposed rows that were not taken

None.

## Seen in this review, not changed

These texts were not part of the proposal. They are left as in version 2 so that this change
holds only the reviewed rows. Each one is a candidate for the next version.

- playwright 41942, L1: "on an unsupported platform that lookup fails" and "should not hit the
  unsupported-platform check" keep the words of the repo's error text that this change removes
  from L2.
- pandas 71232, L1: "the shared fill code transposes the DataFrame ..." points at the shared
  base class code, as the sentence removed from pandas 70966 did.
- pandas 69015, L1: "from the low-level element comparison" retells the issue's stack trace,
  which ends in the compiled testing module that the fix changes.
- playwright 43316, L2: "The MCP cookie list's domain filter" is close to the tool's name
  (browser_cookie_list) split into words. L1 says "the Playwright MCP tool that lists the cookies",
  which is a description. The fixed file is cookies.ts.
