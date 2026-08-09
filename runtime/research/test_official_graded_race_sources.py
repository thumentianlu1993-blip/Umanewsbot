import unittest
from runtime.research.official_graded_race_sources import OfficialSourceError, derive_data_url, parse_official_results, placing, validate_data_url, validate_provider_url


class OfficialSourceTests(unittest.TestCase):
    def test_url_policy_and_dynamic_endpoints(self):
        with self.assertRaises(OfficialSourceError): validate_provider_url("de_deutscher_galopp","http://www.deutscher-galopp.de/2025",year=2025)
        with self.assertRaises(OfficialSourceError): validate_provider_url("de_deutscher_galopp","https://example.com/2025",year=2025)
        self.assertEqual(derive_data_url("uae_era","https://emiratesracing.com/racecard/2025-04-05/1/results",year=2025),"https://emiratesracing.com/ajax/racecard-results?date=2025-04-05&race=1")
        self.assertEqual(derive_data_url("sa_jcsa","https://www.jcsa.sa/en/races/20251205/8",year=2025),"https://www.jcsa.sa/api/meeting-info/en/20251205/8/Results/True")
        qrec_page="https://qrec.gov.qa/race-calendar?racedate=2025-12-20&meetid=11103&raceid=27059&tab=Results"
        qrec_data=derive_data_url("qa_qrec",qrec_page,year=2025)
        self.assertIn("api.qrec.gov.qa/v1/qrec/race/data?",qrec_data)
        self.assertIn("raceid=27059",qrec_data)
        self.assertEqual(validate_data_url("qa_qrec",qrec_data,year=2025),qrec_data)
        with self.assertRaises(OfficialSourceError): validate_provider_url("qa_qrec",qrec_data,year=2025)
        with self.assertRaises(OfficialSourceError): validate_data_url("qa_qrec","https://example.com/2025",year=2025)
        drifted="https://qrec.gov.qa/race-calendar?racedate=2024-12-20&raceid=20250&tab=Results"
        with self.assertRaisesRegex(OfficialSourceError,"year drift"): derive_data_url("qa_qrec",drifted,year=2025)
        drifted_data="https://api.qrec.gov.qa/v1/qrec/race/data?pageaction=jsonracetab&raceid=20250&racedate=2024-12-20"
        with self.assertRaisesRegex(OfficialSourceError,"year drift"): validate_data_url("qa_qrec",drifted_data,year=2025)

    def test_australia(self):
        h="<table><tr><th>Finish</th><th>No.</th><th>Horse</th><th>Trainer</th><th>Jockey</th><th>Margin</th></tr><tr><td>1</td><td>2</td><td><a href='/horse/123'>Example (NZ)</a></td><td>T</td><td>J</td><td>-</td></tr></table>"
        r=parse_official_results("au_racing_australia",h)[0]; self.assertEqual((r["horse_name"],r["provider_horse_id"]),("Example (NZ)","123"))

    def test_australia_selects_one_graded_race_from_multi_race_meeting(self):
        def segment(number, name, distance, grade, horse):
            return f'''<a name="Race{number}"></a>
            <table class="race-title"><tr><th>Race {number} - 1:00PM {name} ({distance} METRES)</th></tr>
            <tr><td>Of $1,000,000. GROUP {grade[-1]}</td></tr></table>
            <table class="race-strip-fields"><tr><th>Finish</th><th>No.</th><th>Horse</th><th>Trainer</th><th>Jockey</th><th>Margin</th></tr>
            <tr><td>1</td><td>{number}</td><td><a href="/horse/{number}">{horse}</a></td><td>T</td><td>J</td><td>-</td></tr></table>'''
        html=segment(1,"SPONSOR OTHER STAKES",1200,"G3","Wrong")+segment(2,"TAB ADRIAN KNOX STAKES",2000,"G3","Right")
        rows=parse_official_results("au_racing_australia",html,race_name="TAB ADRIAN KNOX STAKES",distance="2000",grade="G3")
        self.assertEqual([(row["horse_name"],row["horse_number"]) for row in rows],[("Right","2")])
        with self.assertRaisesRegex(OfficialSourceError,"not found"):
            parse_official_results("au_racing_australia",html,race_name="KNOX STAKES",distance="2000",grade="G3")

    def test_germany(self):
        h="<table><tr><th>Pl.</th><th>Name</th><th>Nr.</th><th>Abstand</th><th>Trainer</th><th>Reiter</th></tr><tr><td>1.</td><td>Partnun</td><td>5</td><td>Kampf</td><td>T</td><td>J</td></tr><tr><td>-</td><td>The Sheriff</td><td>15</td><td></td><td>T2</td><td>J2</td></tr><tr><td colspan='6'>Quoten zu 1 €: Siegwette 7,8 - STARTER: 2</td></tr></table>"
        rows=parse_official_results("de_deutscher_galopp",h)
        self.assertEqual((rows[0]["finish_position"],rows[0]["horse_number"]),(1,"5"))
        self.assertEqual((rows[1]["finish_position"],rows[1]["participant_status"]),(None,"did_not_finish"))

    def test_era(self):
        c=["1","-","Owner","4 (13)","FIRST CLASSS (US) 8 YO - GREY - GELDING","Jockey: Connor Beasley Rating: 119 Time: 2:12.65 Trainer: Doug Watson Weight: 57","","","","FIRST CLASSS (US)","8","119","57","41","10","19"]
        h="<table><tr>"+"".join(f"<td><a href='/horses/2084979'>{x}</a></td>" if i==4 else f"<td>{x}</td>" for i,x in enumerate(c))+"</tr></table>"
        r=parse_official_results("uae_era",h)[0]; self.assertEqual((r["horse_name"],r["trainer_name"]),("FIRST CLASSS (US)","Doug Watson"))

    def test_saudi(self):
        h="<table><tr><th>Place</th><th>Horse Name</th><th>Age &amp; Sex</th><th>Weight</th><th>Rating</th><th>Time</th><th>Margin</th><th>Prize</th></tr><tr><td>1st</td><td></td><td>Wanaameen (KSA) J Christophe Soumillon T Bader Rizaiq O King</td><td>3YO</td><td>57</td><td>85</td><td>2:39.706</td><td>-</td><td>500</td></tr></table>"
        r=parse_official_results("sa_jcsa",h)[0]; self.assertEqual((r["horse_name"],r["trainer_name"]),("Wanaameen (KSA)","Bader Rizaiq"))

    def test_saudi_dash_place_is_did_not_finish(self):
        h="<table><tr><th>Place</th><th>Horse Name</th><th>Age &amp; Sex</th><th>Weight</th><th>Rating</th><th>Time</th><th>Margin</th><th>Prize</th></tr><tr><td>-</td><td></td><td>Scotland Yard (USA) J Luis Morales T Nicolas Bachalard O Owner</td><td>6YO</td><td>57</td><td>108</td><td>-</td><td>-</td><td>-</td></tr></table>"
        r=parse_official_results("sa_jcsa",h)[0]
        self.assertEqual((r["horse_name"],r["finish_position"],r["participant_status"]),("Scotland Yard (USA)",None,"did_not_finish"))

    def test_qatar(self):
        r=parse_official_results("qa_qrec",'{"result":[{"fp":"1","horseId":"Q7","horseName":"Qatar Horse"}]}')[0]; self.assertEqual((r["horse_name"],r["provider_horse_id"]),("Qatar Horse","Q7"))
        page='<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"meeting":{"result":[{"finishPosition":"1st","horseId":"Q8","horseName":"SSR Horse"}]}}}}</script>'
        r=parse_official_results("qa_qrec",page)[0]; self.assertEqual((r["horse_name"],r["provider_horse_id"]),("SSR Horse","Q8"))

    def test_bahrain(self):
        h="<table><tr><th>Position Pos.</th><th>Margin</th><th>Horse Name</th><th>Jockey</th><th>Time</th><th>Trainer</th></tr><tr><td>1st</td><td>-</td><td><a href='/horses/H-7939'>OBEYAN 1893 6 YO - H</a></td><td>J</td><td>1:37.081</td><td>T</td></tr></table>"
        r=parse_official_results("bh_btc",h)[0]; self.assertEqual((r["horse_name"],r["provider_horse_id"]),("OBEYAN 1893","H-7939"))

    def test_dead_heat_positions_are_preserved(self):
        h="<table><tr><th>Pl.</th><th>Name</th><th>Nr.</th><th>Abstand</th><th>Trainer</th><th>Reiter</th></tr>"+"".join(f"<tr><td>1.</td><td>{n}</td><td>{n}</td><td></td><td>T</td><td>J</td></tr>" for n in "AB")+"</table>"
        self.assertEqual([row["finish_position"] for row in parse_official_results("de_deutscher_galopp",h)], [1, 1])

    def test_actual_starter_statuses_are_preserved_and_nonstarters_excluded(self):
        h="<table><tr><th>Pl.</th><th>Name</th><th>Nr.</th><th>Abstand</th><th>Trainer</th><th>Reiter</th></tr>"+"".join(f"<tr><td>{status}</td><td>{name}</td><td>{name}</td><td></td><td>T</td><td>J</td></tr>" for status,name in (("1.","A"),("DNF","B"),("DSQ","C"),("NR","D")))+"</table>"
        rows=parse_official_results("de_deutscher_galopp",h)
        self.assertEqual([(r["horse_name"],r["finish_position"],r["participant_status"]) for r in rows],[("A",1,"finished"),("B",None,"did_not_finish"),("C",None,"disqualified")])
        for status in ("PU", "F", "UR", "Did Not Finish"):
            self.assertEqual(placing(status), (None, "did_not_finish"))

    def test_unknown_result_status_fails_closed(self):
        with self.assertRaisesRegex(OfficialSourceError,"unknown official result status"):
            placing("mystery")


if __name__ == "__main__": unittest.main()
