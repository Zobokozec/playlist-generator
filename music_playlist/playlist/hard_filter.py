"""
Hard filter – SQL dotaz pro získání kandidátů z MariaDB.

Blocking podmínky (nikdy se neodstraňují):
    - m.deleted = 0
    - track musí mít charakteristiku ze kategorie Jazyk (gate)
    - GROUP_CONCAT chars_ids a entity pro následné zpracování v Pythonu
"""
from __future__ import annotations

HARD_FILTER_SQL = """
select m.id as music_id,
	m.album as album_id,
    m.name as title,
    m.name_pronunciation as pronunciation,
    m.notes as description,
    m.duration, -- délka
    m.year, -- rok
	concat('[', GROUP_CONCAT(distinct en.entity), ']') as entity, -- list of entities
    concat('{', GROUP_CONCAT(CONCAT(ch.id, ':', ch.category)), '}') as chars_ids,
    m.recording_code as isrc,
    concat('[', GROUP_CONCAT(distinct ka.keyword), ']') as keywords
    
    
from music_characteristics_view mcv -- charakteristiky hudby a alb
inner join music m on m.id = mcv.subject_1 -- připoj hudbu
inner join music_media mm on m.id = mm.music -- připoj nosiče
inner join characteristics ch on mcv.subject_2 = ch.id -- připoj charakteristiky
inner join (
	SELECT eu.entity, eu.subject_id as track_id -- načti music.id a entitu
	from entity_usage eu
    INNER JOIN binary_assoc eur ON eur.subject_1 = eu.id 
		AND eur.subject_type_1 = 14 -- entity_usage
        AND eur.subject_type_2 = 13 -- role_entity
        AND eur.assoc_type = 3 -- entityUsageRole
    where eu.subject_type in (6, 12) -- usage je v music, music album
		and eur.subject_2 in (5,6) -- role je skupina nebo interpret
	group by eu.entity, track_id -- set entity a hudbu
	order by track_id, eu.entity -- seřaď podle entity a hudby
    ) en on m.id = en.track_id
left join keyword_assoc ka on m.id = ka.subject_id and ka.subject_type = 6

where m.deleted = 0 -- není smazaná hudba 
    and duration > 0 -- je delší než 0
    and year is not null -- má zadaný rok
    and mm.medium_type in (199,205) -- je na CD nebo PC
    and not exists(
		select 1 
        from music_characteristics_view mcx 
        where mcx.subject_1 = m.id 
        and mcx.subject_2 in (select id from characteristics where category = 3)
        ) -- nemá technickou charakteristiku
	and (year > 2000 or ch.id = 904) -- je novější než 2000 nebo je evergreen
 group by m.id

"""


def run_hard_filter(twar) -> list[dict]:
    """Spustí hard filter dotaz a vrátí raw řádky.

    Args:
        twar: MariaDB klient s metodou dotaz_dict(sql, params)

    Returns:
        Seznam dict řádků z DB.
    """
    return twar.dotaz_dict(HARD_FILTER_SQL)
