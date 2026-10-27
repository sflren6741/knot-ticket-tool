"""Offline browser regression checks. Run with Python + Playwright and installed Edge."""
import json
from pathlib import Path
import tempfile
import unittest
import re
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from threading import Thread

from playwright.sync_api import sync_playwright


class TicketInteractions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="msedge", headless=True)
        cls.url = Path(__file__).with_name("index.html").as_uri()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 1000})
        self.page = self.context.new_page()
        self.errors, self.requests = [], []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("request", lambda req: self.requests.append(req.url))
        self.page.goto(self.url)

    def tearDown(self):
        errors = self.errors[:]
        network = [r for r in self.requests if r.startswith(("http:", "https:")) and r != self.url]
        self.context.close()
        self.assertEqual(errors, [], "Uncaught browser error")
        self.assertEqual(network, [], "Unexpected network request")

    def js(self, expression, arg=None):
        return self.page.evaluate(expression, arg)

    def card(self, ticket_id):
        return self.page.locator(f'#board [data-ticket="{ticket_id}"]')

    def select(self, *ids):
        for i, ticket_id in enumerate(ids):
            self.card(ticket_id).click(modifiers=["Shift"] if i else [])
        self.assertEqual(set(self.js("[...selected]")), set(ids))

    def drag(self, locator, dx=75, dy=35):
        rect = locator.bounding_box()
        x, y = rect["x"] + rect["width"] / 2, rect["y"] + 35
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + dx, y + dy, steps=8)
        self.page.mouse.up()

    def apply(self):
        self.page.locator("#edit-apply").click()

    def drop_on(self, source, target, release=True):
        a, b = self.card(source).bounding_box(), self.card(target).bounding_box()
        self.page.mouse.move(a['x'] + a['width']/2, a['y'] + min(24,a['height']/2))
        self.page.mouse.down()
        self.page.mouse.move(b['x'] + b['width']/2, b['y'] + min(24,b['height']/2), steps=12)
        if release:
            self.page.mouse.up()

    def test_01_initial_and_filter_empty_project(self):
        self.assertEqual(self.page.locator(".ticket").count(), 7)
        self.page.locator('[data-project="all"]').click()
        self.assertEqual(self.page.locator(".ticket").count(), 10)
        self.page.locator("#add-project").click()
        self.page.locator("#new-project-name").fill("新規プロジェクト")
        self.apply()
        self.assertEqual(self.page.locator(".ticket").count(), 0)
        self.page.locator("#new-button").click()
        self.assertEqual(self.page.locator(".ticket").count(), 1)

    def test_02_drag_parent_and_grandchildren(self):
        before = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        zoom = self.js("zoom")
        self.drag(self.card("WEB-001"))
        after = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        for a, b in zip(before, after):
            self.assertAlmostEqual(b["x"] - a["x"], 75 / zoom if a["id"].startswith("WEB") else 0, delta=.001)
            self.assertAlmostEqual(b["y"] - a["y"], 35 / zoom if a["id"].startswith("WEB") else 0, delta=.001)
        self.page.keyboard.press("Control+z")
        self.assertEqual(self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))"), before)
        self.page.keyboard.press("Control+y")
        self.assertEqual(self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))"), after)

    def test_03_marquee_at_zoom_and_pan(self):
        c = self.page.locator("#canvas-scroll").bounding_box()
        self.page.mouse.move(c["x"] + 20, c["y"] + 20)
        self.page.mouse.wheel(20, 40)
        self.page.keyboard.down("Control")
        self.page.mouse.wheel(0, 90)
        self.page.keyboard.up("Control")
        self.page.wait_for_timeout(80)
        a, b = self.card("WEB-002").bounding_box(), self.card("WEB-003").bounding_box()
        self.page.mouse.move(a["x"] - 8, a["y"] - 8)
        self.page.keyboard.down("Shift")
        self.page.mouse.down()
        self.page.mouse.move(b["x"] + b["width"] + 8, b["y"] + b["height"] + 8, steps=8)
        self.page.mouse.up()
        self.page.keyboard.up("Shift")
        self.assertEqual(set(self.js("[...selected]")), {"WEB-002", "WEB-003"})
        self.card("WEB-002").click(button="right")
        self.assertTrue(self.page.locator('[data-action="bulk"]').is_visible())
        self.assertTrue(self.page.locator('[data-action="group"]').is_visible())
        self.assertEqual(self.page.locator('[data-action="child"]').count(), 0)

    def test_04_no_double_movement_and_groups(self):
        self.select("WEB-001", "WEB-002")
        before = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        zoom = self.js("zoom")
        self.drag(self.card("WEB-002"), 40, 20)
        after = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        for a, b in zip(before, after):
            self.assertAlmostEqual(b["x"] - a["x"], 40 / zoom if a["id"].startswith("WEB") else 0)
        self.page.locator("#undo-button").click()
        self.select("WEB-002", "WEB-004")
        self.card("WEB-002").click(button="right")
        self.page.locator('[data-action="group"]').click()
        self.page.locator("#group-name").fill("制作チーム")
        self.apply()
        self.assertEqual(self.js("groups[0].ids"), ["WEB-002", "WEB-004"])
        self.select("WEB-002")
        before = self.js("tickets.map(t=>({id:t.id,x:t.x}))")
        self.drag(self.card("WEB-002"), 30, 0)
        after = self.js("tickets.map(t=>({id:t.id,x:t.x}))")
        moving = {"WEB-002", "WEB-004", "WEB-005", "WEB-007"}
        for a, b in zip(before, after):
            self.assertAlmostEqual(b["x"] - a["x"], 30 / zoom if a["id"] in moving else 0)
        self.assertEqual(self.page.locator(".group-outline").count(), 1)

    def test_05_bulk_edits_exact_selection_and_date_validation(self):
        self.select("WEB-002", "WEB-003")
        self.page.locator("#bulk-edit").click()
        self.page.locator("#bulk-start").fill("2026-11-20")
        self.apply()
        self.assertTrue(self.page.locator("#edit-dialog").is_visible())
        self.assertNotEqual(self.page.locator("#edit-error").inner_text(), "")
        self.page.locator("#bulk-start").fill("2026-10-27")
        self.page.locator("#bulk-due").fill("2026-11-20")
        self.page.locator("#bulk-assignee").fill("Ren")
        self.page.locator("#bulk-project").select_option("event")
        self.page.locator("#bulk-state").select_option(label="完了")
        self.apply()
        data = self.js("tickets.map(t=>({id:t.id,project:t.project,assignee:t.assignee,state:t.state,due:t.due}))")
        for t in data:
            if t["id"] in ["WEB-002", "WEB-003"]:
                self.assertEqual((t["project"], t["assignee"], t["state"], t["due"]), ("event", "Ren", "完了", "2026-11-20"))
        self.assertEqual(self.js("getTicket('WEB-005').project"), "website")
        self.assertEqual(self.page.locator(".ticket").count(), 5)
        self.page.locator("#undo-button").click()
        self.assertEqual(self.page.locator(".ticket").count(), 7)

    def test_06_shortcuts_and_input_guard(self):
        self.select("WEB-002")
        self.page.keyboard.press("Tab")
        self.assertEqual(self.js("tickets.length"), 11)
        child = self.js("selectedId")
        self.assertEqual(self.js("getTicket(selectedId).parent"), "WEB-002")
        self.page.locator("#detail-title").fill("子チケット")
        self.page.keyboard.press("Tab")  # Moves focus; never creates another ticket.
        self.assertEqual(self.js("tickets.length"), 11)
        self.card(child).click()
        self.page.keyboard.press("Control+Enter")
        self.assertEqual(self.js("tickets.length"), 12)
        self.assertTrue(self.js("dependencies.some(d=>d[0]===tickets[tickets.length-2].id&&d[1]===selectedId)"))
        self.page.locator("#detail-description").focus()
        self.page.keyboard.press("Control+Enter")
        self.assertEqual(self.js("tickets.length"), 12)

    def test_07_background_pan_zoom_double_click(self):
        c = self.page.locator("#canvas-scroll").bounding_box()
        x, y = round(c["x"] + 30), round(c["y"] + 35)
        initial = self.js("({...pan})")
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + 35, y + 25, steps=6)
        self.page.mouse.up()
        self.assertAlmostEqual(self.js("pan.x"), initial["x"] + 35)
        self.assertAlmostEqual(self.js("pan.y"), initial["y"] + 25)
        z = self.js("zoom")
        self.page.mouse.move(x, y)
        self.page.mouse.wheel(0, 90)
        self.page.wait_for_timeout(80)
        self.assertEqual(self.js("zoom"), z)
        point = self.js("([x,y])=>worldPoint(x,y)", [x, y])
        self.page.keyboard.down("Control")
        self.page.mouse.wheel(0, -150)
        self.page.keyboard.up("Control")
        self.page.wait_for_timeout(80)
        self.assertGreater(self.js("zoom"), z)
        point_after = self.js("([x,y])=>worldPoint(x,y)", [x, y])
        self.assertAlmostEqual(point["x"], point_after["x"])
        self.assertAlmostEqual(point["y"], point_after["y"])
        self.page.mouse.dblclick(x, y)
        self.assertEqual(self.js("tickets.length"), 11)

    def test_08_edit_schedule_and_reload(self):
        self.page.locator("#detail-title").fill("Changed title")
        self.page.locator("#detail-title").press("Tab")
        self.page.locator("#detail-due").fill("2027-01-10")
        self.page.locator("#detail-due").press("Tab")
        self.page.locator("#tab-schedule").click()
        self.assertIn("2027-01-10", self.page.locator(".schedule-title").inner_text())
        self.assertIn("Changed title", self.page.locator("#gantt-chart").inner_text())
        self.page.locator('button[data-scale="month"]').click()
        self.assertIn('2027-01-10',self.page.locator('.gantt-bar[data-ticket="WEB-002"]').get_attribute('aria-label'))
        self.page.reload()
        self.assertEqual(self.js("getTicket('WEB-002').title"), "Changed title")
        self.assertEqual(self.js("getTicket('WEB-002').due"), "2027-01-10")

    def test_09_attachments_thumbnail_and_browser_recovery(self):
        self.page.locator("#attachment-input").set_input_files([
            {"name": "note.txt", "mimeType": "text/plain", "buffer": b"local attachment"},
            {"name": "image.svg", "mimeType": "image/svg+xml", "buffer": b'<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect width="50" height="50" fill="blue"/></svg>'},
        ])
        self.page.wait_for_function("() => getTicket('WEB-002').attachments?.length===2")
        self.assertEqual(self.page.locator("[data-download]").count(), 2)
        self.page.locator("#thumbnail-toggle").uncheck()
        self.assertEqual(self.card("WEB-002").locator("img").count(), 0)
        self.page.locator("#thumbnail-toggle").check()
        self.assertEqual(self.card("WEB-002").locator("img").count(), 1)
        data = json.loads(self.js("localStorage.getItem(STORE)"))
        ticket = next(t for t in data["tickets"] if t["id"] == "WEB-002")
        self.assertEqual(len(ticket["attachments"]), 2)
        self.assertEqual(ticket["attachments"][0]["data"], "data:text/plain;base64,bG9jYWwgYXR0YWNobWVudA==")
        self.page.reload()
        self.assertEqual(self.page.locator("[data-download]").count(), 2)

    def test_10_connections_cycles_and_missing_parent_filter(self):
        self.select("WEB-003")
        self.page.locator("#parent-select").select_option("WEB-006")
        self.assertEqual(self.js("getTicket('WEB-003').parent"), "WEB-001")
        self.select("WEB-004")
        self.page.locator("#link-next").click()
        self.card("WEB-003").click()
        self.assertTrue(self.js("dependencies.some(d=>d[0]==='WEB-004'&&d[1]==='WEB-003')"))
        self.select("WEB-003")
        self.page.locator("#link-next").click()
        self.card("WEB-004").click()
        self.assertFalse(self.js("dependencies.some(d=>d[0]==='WEB-003'&&d[1]==='WEB-004')"))
        self.select("WEB-001")
        self.page.locator("#detail-project").select_option("event")
        self.assertEqual(self.page.locator(".ticket").count(), 6)
        self.page.locator("#arrange-button").click()  # Hidden parent must not break edges/layout.

    def test_11_arrange_no_overlap_fit_negative_coordinates(self):
        self.js("getTicket('WEB-002').x=-500;getTicket('WEB-002').y=-300;renderAll();fitBoard()")
        c = self.page.locator("#canvas-scroll").bounding_box()
        for card in self.page.locator(".ticket").all():
            r = card.bounding_box()
            self.assertGreaterEqual(r["x"], c["x"])
            self.assertGreaterEqual(r["y"], c["y"])
            self.assertLessEqual(r["x"] + r["width"], c["x"] + c["width"])
        self.page.locator("#arrange-button").click()
        boxes = self.js("visibleTickets().map(t=>({x:t.x,y:t.y,w:224,h:cardHeight(t)}))")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])
        self.assertTrue(self.js("visibleTickets().every(t=>(t.x-40)%320===0&&t.y>=64)"))
        self.assertTrue(self.js("['WEB-002','WEB-003','WEB-004'].every(id=>getTicket(id).x===360)"))
        self.assertTrue(self.js("['WEB-005','WEB-006','WEB-007'].every(id=>getTicket(id).x===680)"))
        self.assertTrue(self.js("['WEB-002','WEB-003','WEB-004'].every((id,i)=>getTicket(id).y===getTicket(['WEB-005','WEB-006','WEB-007'][i]).y)"))
        self.page.screenshot(path=str(Path(tempfile.gettempdir()) / "knot-arranged.png"))

    def test_12_escape_drag_cancel(self):
        before = self.js("snapshot()")
        r = self.card("WEB-002").bounding_box()
        x, y = r["x"] + 40, r["y"] + 30
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + 50, y + 30, steps=5)
        self.page.keyboard.press("Escape")
        self.page.mouse.up()
        self.assertEqual(self.js("snapshot()"), before)
        self.assertEqual(self.js("undoStack.length"), 0)

    def test_13_validation_rejects_cycles_without_mutation(self):
        data = json.loads(self.js("snapshot()"))
        before = self.js('snapshot()')
        data["dependencies"].append(["WEB-003", "WEB-002"])
        self.assertFalse(self.js("data => {try{validateDocument(data);return true;}catch(e){return false;}}",data))
        self.assertEqual(self.js('snapshot()'),before)
        self.assertEqual(self.page.locator('#export-button,#import-input').count(),0)

    def test_14_cross_filter_group_drag_and_delete_undo(self):
        self.select("WEB-002", "WEB-004")
        self.page.locator("#group-selection").click()
        self.apply()
        self.js("getTicket('WEB-004').project='event';renderAll();fitBoard()")
        x = self.js("getTicket('WEB-004').x")
        z = self.js("zoom")
        self.select("WEB-002")
        self.drag(self.card("WEB-002"), 30, 0)
        self.assertAlmostEqual(self.js("getTicket('WEB-004').x") - x, 30 / z)
        self.card("WEB-002").click(button="right")
        self.page.locator('[data-action="delete"]').click()
        self.apply()
        self.assertIsNone(self.js("getTicket('WEB-002')||null"))
        self.assertIsNone(self.js("getTicket('WEB-005').parent"))
        self.page.locator("#undo-button").click()
        self.assertEqual(self.js("getTicket('WEB-005').parent"), "WEB-002")

    def test_15_html_escaping_and_narrow_layout(self):
        self.page.locator("#detail-title").fill('<img src=x onerror="alert(1)">')
        self.page.locator("#detail-title").press("Tab")
        self.assertIn("<img", self.card("WEB-002").inner_text())
        self.assertEqual(self.card("WEB-002").locator("img").count(), 1)
        self.page.set_viewport_size({"width": 1100, "height": 800})
        self.assertTrue(self.page.locator("#new-button").is_visible())
        self.page.locator("#tab-schedule").click()
        self.page.screenshot(path=str(Path(tempfile.gettempdir()) / "knot-schedule.png"))
        work = self.page.locator('.work-row').bounding_box()
        self.assertLessEqual(work['y']+work['height'],800)

    def test_16_unblurred_text_is_saved_and_edit_is_one_undo(self):
        original = self.js("getTicket('WEB-002').description")
        self.page.locator("#detail-description").fill("Draft saved before blur")
        self.page.reload()
        self.assertEqual(self.page.locator("#detail-description").input_value(), "Draft saved before blur")
        self.page.locator("#detail-description").fill("Second edit")
        self.page.locator("#undo-button").click()
        self.assertEqual(self.js("getTicket('WEB-002').description"), "Draft saved before blur")
        self.assertNotEqual(original, "Draft saved before blur")

    def test_17_save_failures_are_visible_and_corrupt_data_is_preserved(self):
        self.js("localStorage.setItem(STORE,'invalid saved data')")
        self.page.reload()
        self.assertTrue(self.js("storageBlocked"))
        self.page.locator("#new-button").click()
        self.assertEqual(self.js("localStorage.getItem(STORE)"), "invalid saved data")
        self.context.close()
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 1000})
        self.page = self.context.new_page()
        self.page.goto(self.url)
        self.js("() => {Storage.prototype.setItem=function(){throw new DOMException('quota exceeded','QuotaExceededError')};}")
        self.page.locator("#new-button").click()
        self.assertTrue(self.js('storageIssue.length>0'))
        self.assertEqual(self.js("tickets.length"), 11)

    def test_18_ungroup_and_keyboard_menu(self):
        self.select("WEB-002", "WEB-004")
        self.page.locator("#group-selection").click()
        self.apply()
        self.card("WEB-002").click(button="right")
        self.page.keyboard.press("End")
        self.assertEqual(self.js("document.activeElement.dataset.action"), "delete")
        self.page.keyboard.press("Home")
        self.assertEqual(self.js("document.activeElement.dataset.action"), "bulk")
        self.page.locator('[data-action="ungroup"]').click()
        self.assertEqual(self.js("groups.length"), 0)
        self.page.locator("#undo-button").click()
        self.assertEqual(self.js("groups.length"), 1)

    def test_19_collapse_nested_state_and_schedule(self):
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.assertEqual(self.page.locator('.ticket').count(), 6)
        self.assertFalse(self.card('WEB-005').count())
        self.assertEqual(self.page.locator('[data-collapse="WEB-002"]').get_attribute('aria-expanded'), 'false')
        self.page.locator('[data-collapse="WEB-001"]').click()
        self.assertEqual(self.page.locator('.ticket').count(), 1)
        self.page.locator('[data-collapse="WEB-001"]').click()
        self.assertEqual(self.page.locator('.ticket').count(), 6)
        self.assertFalse(self.card('WEB-005').count())
        self.page.locator('#tab-schedule').click()
        self.assertEqual(self.page.locator('.gantt-row').count(), 7)
        self.page.locator('#tab-tickets').click()
        self.page.reload()
        self.assertEqual(self.page.locator('.ticket').count(), 6)
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.assertEqual(self.page.locator('.ticket').count(), 7)

    def test_20_collapsed_descendants_move_and_undo(self):
        self.page.locator('[data-collapse="WEB-001"]').click()
        before = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        z = self.js('zoom')
        self.drag(self.card('WEB-001'), 45, 25)
        after = self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))")
        for a,b in zip(before,after):
            self.assertAlmostEqual(b['x']-a['x'],45/z if a['id'].startswith('WEB') else 0,delta=.001)
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js("tickets.map(t=>({id:t.id,x:t.x,y:t.y}))"),before)
        self.page.locator('#undo-button').click()
        self.assertEqual(self.page.locator('.ticket').count(),7)

    def test_21_collapsed_children_not_selected_and_keyboard_toggle(self):
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.card('WEB-001').focus()
        self.page.keyboard.press('Control+a')
        self.assertNotIn('WEB-005',self.js('[...selected]'))
        self.assertEqual(self.js('selected.size'),6)
        self.page.locator('[data-collapse="WEB-002"]').focus()
        self.page.keyboard.press('Enter')
        self.assertEqual(self.page.locator('.ticket').count(),7)
        self.assertEqual(self.js('tickets.length'),10)
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.page.keyboard.press('Control+z')
        self.assertEqual(self.page.locator('.ticket').count(),7)
        self.page.keyboard.press('Control+y')
        self.assertEqual(self.page.locator('.ticket').count(),6)

    def test_22_variable_grid_with_group_and_long_title(self):
        self.select('WEB-002','WEB-004')
        self.page.locator('#group-selection').click()
        self.apply()
        self.select('WEB-002')
        self.page.locator('#detail-title').fill('Long title '*25)
        self.page.locator('#detail-title').press('Tab')
        self.page.locator('#arrange-button').click()
        self.assertGreater(len(set(self.js('boardTickets().map(t=>cardHeight(t))'))), 1)
        self.assertTrue(self.js("cardHeight(getTicket('WEB-002'))>cardHeight(getTicket('WEB-003'))"))
        once=self.js('snapshot()')
        self.page.locator('#arrange-button').click()
        self.assertEqual(self.js('snapshot()'),once)
        self.assertTrue(self.js("[...document.querySelectorAll('#edge-paths path')].every(p=>p.getAttribute('d').includes('C'))"))
        self.page.screenshot(path=str(Path(tempfile.gettempdir())/'knot-grid-v3.png'))

    def test_23_add_child_expands_parent_and_keeps_old_documents_compatible(self):
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.select('WEB-002')
        self.page.keyboard.press('Tab')
        self.assertFalse(self.js("collapsed.has('WEB-002')"))
        self.assertEqual(self.page.locator('.ticket').count(),8)
        self.js('() => { const data=JSON.parse(snapshot());delete data.collapsed;validateDocument(data);restore(data);renderAll(); }')
        self.assertEqual(self.js('collapsed.size'),0)


    def test_37_deadline_boundaries_and_state_exclusions(self):
        self.page.clock.install(time=datetime.fromisoformat('2026-10-27T12:00:00+09:00'))
        self.js("""() => {
          tickets.forEach(t=>{t.start='2026-10-20';t.due='2026-11-03';t.state='未着手';});
          getTicket('WEB-001').due='2026-11-04';
          getTicket('WEB-002').due='2026-10-26';
          getTicket('WEB-003').due='2026-10-27';
          getTicket('WEB-004').state='メモ';
          getTicket('WEB-005').state='完了';
          getTicket('WEB-006').state='非実施';
          renderAll();
        }""")
        self.page.locator('[data-focus="soon"]').click()
        self.assertEqual(set(self.page.locator('.ticket.focus-match').evaluate_all('(els)=>els.map(el=>el.dataset.ticket)')), {'WEB-003', 'WEB-007'})
        self.assertEqual(self.page.locator('.ticket').count(), 7)
        self.assertIn('本日期限', self.card('WEB-003').inner_text())
        self.assertIn('あと7日', self.card('WEB-007').inner_text())
        self.page.locator('[data-focus="overdue"]').click()
        self.assertEqual(self.page.locator('.ticket.focus-match').evaluate_all('(els)=>els.map(el=>el.dataset.ticket)'), ['WEB-002'])
        self.assertIn('1日超過', self.card('WEB-002').inner_text())
        self.page.locator('#tab-schedule').click()
        self.assertEqual(self.page.locator('.gantt-row').count(), 6)
        self.assertEqual(self.page.locator('.gantt-row:not(.focus-muted)').count(), 1)
        self.page.locator('[data-focus="all"]').click()
        self.assertEqual(self.page.locator('.gantt-row').count(), 6)
        self.assertEqual(self.page.locator('.schedule-memos').first.locator('button').count(), 1)

    def test_38_readiness_ancestors_cross_project_and_reasons(self):
        self.page.clock.install(time=datetime.fromisoformat('2026-10-27T12:00:00+09:00'))
        self.js("""() => {
          tickets.forEach(t=>{t.state='完了';t.start='2026-10-20';});
          getTicket('WEB-005').state='未着手';getTicket('WEB-006').state='未着手';
          getTicket('WEB-004').state='保留';getTicket('WEB-007').state='未着手';getTicket('WEB-007').start='2026-10-28';
          getTicket('EVT-002').state='未着手';dependencies.push(['EVT-002','WEB-002']);renderAll();
        }""")
        self.assertIn('前工程待ち', self.card('WEB-005').locator('.readiness-mark').get_attribute('title'))
        self.assertIn('保留中', self.card('WEB-004').locator('.readiness-mark').get_attribute('title'))
        self.assertFalse(self.js("readiness(getTicket('WEB-006')).ready"))
        self.js("getTicket('EVT-002').state='非実施';renderAll()")
        self.assertTrue(self.js("readiness(getTicket('WEB-005')).ready"))
        self.assertFalse(self.js("readiness(getTicket('WEB-006')).ready"))  # Its completed parent still has an unfinished child.
        self.js("getTicket('WEB-005').state='完了';renderAll()")
        self.assertTrue(self.js("readiness(getTicket('WEB-006')).ready"))
        self.js("getTicket('WEB-006').state='完了';renderAll()")
        self.assertIn('開始予定', self.card('WEB-007').locator('.readiness-mark').get_attribute('title'))
        self.js("getTicket('WEB-001').state='未着手';renderAll()")
        self.assertIn('子チケット', self.card('WEB-001').locator('.readiness-mark').get_attribute('title'))
        self.page.locator('[data-focus="ready"]').click()
        self.assertEqual(self.page.locator('.ticket').count(), 7)
        self.assertEqual(self.page.locator('.ticket.focus-muted').count(), 7)
        self.assertIn('0件に注目', self.page.locator('#view-count').inner_text())

    def test_39_memo_reference_inline_text_and_optional_dates(self):
        self.card('WEB-002').click(button='right')
        self.page.locator('[data-action="memo"]').click()
        memo = self.js('selectedId')
        self.assertEqual(self.js('getTicket(selectedId).state'), 'メモ')
        self.assertEqual(self.js('references.length'), 1)
        self.assertEqual(self.js('getTicket(selectedId).start'), '')
        self.page.locator('#detail-description').fill('<img src=x onerror=alert(1)>\n参考の内容')
        self.page.locator('#detail-description').press('Tab')
        self.assertIn('参考の内容', self.card(memo).locator('.memo-preview').inner_text())
        self.assertEqual(self.card(memo).locator('img').count(), 0)
        self.assertEqual(self.page.locator('.reference-path').count(), 1)
        before=self.js("readiness(getTicket('WEB-002'))")
        self.js("beginReference('WEB-002');completeLink('WEB-003')")
        self.assertEqual(self.js("readiness(getTicket('WEB-002'))"), before)
        self.page.reload()
        self.assertEqual(self.js('references.length'), 2)
        self.js('validateDocument(JSON.parse(snapshot()))')
        self.assertIn('参考の内容', self.card(memo).inner_text())
        self.js('selectTicket('+json.dumps(memo)+')')
        self.page.locator('#detail-state').select_option('非実施')
        self.assertTrue(self.js('validDate(getTicket(selectedId).start)&&validDate(getTicket(selectedId).due)'))
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('getTicket(selectedId).state'), 'メモ')
        self.assertEqual(self.js('getTicket(selectedId).due'), '')

    def test_40_project_menu_rename_delete_retains_cards_and_undo(self):
        self.assertEqual(self.page.locator('#rename-project').count(), 0)
        self.page.locator('[data-project="event"]').click(button='right')
        self.page.locator('[data-action="rename-project"]').click()
        self.page.locator('#new-project-name').fill('イベント改名')
        self.apply()
        self.assertEqual(self.js('projectNames.event'), 'イベント改名')
        self.assertEqual(self.js('project'), 'website')  # Rename the clicked project, not the active one.
        self.page.locator('[data-project="event"]').focus()
        self.page.keyboard.press('Shift+F10')
        self.page.locator('[data-action="delete-project"]').click()
        self.page.locator('#edit-cancel').click()
        self.assertEqual(self.js('tickets.length'), 10)
        self.assertEqual(self.js('projectNames.event'), 'イベント改名')
        self.page.locator('[data-project="event"]').click(button='right')
        self.page.locator('[data-action="delete-project"]').click()
        self.page.locator('#project-destination').select_option('website')
        self.apply()
        self.assertIsNone(self.js('projectNames.event||null'))
        self.assertEqual(self.js('tickets.filter(t=>t.project==="website").length'), 10)
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('projectNames.event'), 'イベント改名')
        self.assertEqual(self.js('tickets.filter(t=>t.project==="event").length'), 3)

    def test_41_last_project_delete_and_uncategorized_reuse(self):
        self.js("""() => {tickets.forEach(t=>t.project='website');delete projectNames.event;renderAll();deleteProject('website');}""")
        self.apply()
        self.assertEqual(self.js("Object.values(projectNames).filter(v=>v==='未分類').length"), 1)
        self.assertEqual(self.js('tickets.length'), 10)
        self.js('validateDocument(JSON.parse(snapshot()))')
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('projectNames.website'), 'サービスサイト刷新')

    def test_42_image_containment_compact_cards_and_folding_focus(self):
        self.page.clock.install(time=datetime.fromisoformat('2026-10-27T12:00:00+09:00'))
        self.page.locator('#attachment-input').set_input_files({
            'name':'portrait.svg', 'mimeType':'image/svg+xml',
            'buffer':b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="800"><rect width="100" height="800" fill="blue"/></svg>'})
        self.page.wait_for_function("()=>getTicket('WEB-002').attachments?.length===1")
        self.assertEqual(self.card('WEB-002').locator('img').evaluate('(e)=>getComputedStyle(e).objectFit'), 'contain')
        self.assertLessEqual(self.card('WEB-002').locator('img').evaluate('e=>e.offsetHeight'), 160)
        self.assertGreater(self.js("cardHeight(getTicket('WEB-002'))-cardHeight(getTicket('WEB-003'))"), 140)
        self.assertEqual(self.page.locator('.card-spacer').count(), 0)
        self.page.locator('#arrange-button').click()
        self.assertTrue(self.js("getTicket('WEB-003').y>=getTicket('WEB-002').y+cardHeight(getTicket('WEB-002'))+60"))
        self.js("tickets.forEach(t=>{t.state='未着手';t.start='2026-10-20';});getTicket('WEB-002').state='完了';getTicket('WEB-003').state='完了';getTicket('WEB-005').state='完了';getTicket('WEB-006').state='完了';renderAll();fitBoard()")
        self.page.locator('[data-collapse="WEB-004"]').click()
        self.assertEqual(self.card('WEB-007').count(), 0)
        self.page.locator('[data-focus="ready"]').click()
        self.assertEqual(self.card('WEB-007').count(), 0)
        self.page.locator('[data-focus="all"]').click()
        self.assertEqual(self.card('WEB-007').count(), 0)
        self.assertTrue(self.js("collapsed.has('WEB-004')"))


    def test_44_arrange_keeps_zoom_and_pan_until_explicit_fit(self):
        self.js("zoom=.9;pan={x:-120,y:65};getTicket('WEB-004').x=1000;applyZoom()")
        view = self.js('({zoom,pan})')
        self.page.locator('#arrange-button').click()
        self.assertEqual(self.js('({zoom,pan})'), view)
        self.assertEqual(self.js("getTicket('WEB-004').x"), 360)
        self.page.locator('#fit-button').click()
        self.assertNotEqual(self.js('({zoom,pan})'), view)

    def test_45_focus_preserves_geometry_selection_and_schedule(self):
        before = self.js('({document:snapshot(),zoom,pan,selected:[...selected],undo:undoStack.length})')
        boxes = self.page.locator('.ticket').evaluate_all('(els)=>els.map(el=>({id:el.dataset.ticket,rect:el.getBoundingClientRect().toJSON()}))')
        for mode in ['ready','soon','overdue','all']:
            self.page.locator(f'[data-focus="{mode}"]').click()
            self.assertEqual(self.page.locator('.ticket').count(), 7)
            self.assertEqual(self.js('({document:snapshot(),zoom,pan,selected:[...selected],undo:undoStack.length})'), before)
            self.assertEqual(self.page.locator('.ticket').evaluate_all('(els)=>els.map(el=>({id:el.dataset.ticket,rect:el.getBoundingClientRect().toJSON()}))'), boxes)
        self.page.locator('[data-focus="ready"]').click()
        self.assertTrue(self.card('WEB-002').evaluate("el=>el.classList.contains('focus-muted')"))
        self.card('WEB-002').click()
        self.assertEqual(self.js('focusMode'), 'ready')
        self.assertEqual(self.js('selectedId'), 'WEB-002')
        self.page.locator('#tab-schedule').click()
        ticks = self.page.locator('.gantt-days').inner_html()
        self.page.locator('[data-focus="overdue"]').click()
        self.assertEqual(self.page.locator('.gantt-row').count(), 7)
        self.assertEqual(self.page.locator('.gantt-days').inner_html(), ticks)
        self.page.locator('button[data-scale="month"]').click()
        self.assertEqual(self.page.locator('.gantt-row').count(), 7)
        self.assertGreater(self.page.locator('.gantt-row.focus-muted').count(), 0)

    def test_46_minimal_cards_and_details_explanations(self):
        text = self.page.locator('#board').inner_text()
        self.assertNotRegex(text, r'WEB-\d|親チケット|子チケット|前工程待ち|前工程の待ちなし|今取り組める')
        self.assertEqual(self.page.locator('.ticket-head,.child-count,.card-reason').count(), 0)
        self.assertEqual(self.page.locator('.readiness-mark').count(), 7)
        self.assertIn('WEB-002', self.page.locator('.detail-id').inner_text())
        self.assertEqual(self.page.locator('.detail-kind').inner_text(), '子チケット')
        self.assertIn('子チケット', self.page.locator('.detail-readiness').inner_text())
        self.assertIn('着手', self.card('WEB-005').locator('.readiness-mark').get_attribute('aria-label'))

    def test_47_workflow_anchors_bottom_to_top(self):
        for edge in self.page.locator('.workflow-path').all():
            a, b = edge.get_attribute('data-from'), edge.get_attribute('data-to')
            numbers = list(map(float, re.findall(r'-?\d+(?:\.\d+)?', edge.get_attribute('d'))))
            expected = self.js("([a,b])=>{const x=getTicket(a),y=getTicket(b);return [x.x+112,x.y+cardHeight(x)+1,y.x+112,y.y-2]}", [a,b])
            self.assertEqual(numbers[:2], expected[:2])
            self.assertEqual(numbers[-2:], expected[-2:])
        self.js("getTicket('WEB-003').y=-100;renderAll()")
        edge = self.page.locator('.workflow-path[data-from="WEB-002"][data-to="WEB-003"]')
        self.assertEqual(edge.get_attribute('d').count('C'), 2)
        self.assertEqual(list(map(float,re.findall(r'-?\d+(?:\.\d+)?',edge.get_attribute('d'))))[-1], -102)

    def test_48_drag_child_choice_is_atomic_and_undoable(self):
        before = self.js('snapshot()')
        viewport = self.js('({zoom,pan})')
        self.drop_on('WEB-004','WEB-002')
        self.assertTrue(self.page.locator('#edit-dialog').is_visible())
        self.assertEqual(self.js('snapshot()'), before)
        self.page.locator('input[name="relationship-kind"][value="child"]').check()
        self.apply()
        self.assertEqual(self.js("getTicket('WEB-004').parent"), 'WEB-002')
        self.assertEqual(self.js('({zoom,pan})'), viewport)
        self.assertEqual(self.js('undoStack.length'), 1)
        self.assertEqual(self.js("getTicket('WEB-007').parent"), 'WEB-004')
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('snapshot()'), before)
        self.page.locator('#redo-button').click()
        self.assertEqual(self.js("getTicket('WEB-004').parent"), 'WEB-002')

    def test_49_drag_after_replaces_reverse_edge(self):
        before = self.js('snapshot()')
        self.drop_on('WEB-002','WEB-003')
        self.page.locator('input[name="relationship-kind"][value="after"]').check()
        self.apply()
        self.assertTrue(self.js("dependencies.some(([a,b])=>a==='WEB-003'&&b==='WEB-002')"))
        self.assertFalse(self.js("dependencies.some(([a,b])=>a==='WEB-002'&&b==='WEB-003')"))
        self.assertEqual(self.js("getTicket('WEB-002').parent"), 'WEB-001')
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('snapshot()'), before)

    def test_50_drag_parallel_shares_parent_removes_direct_order(self):
        self.drop_on('WEB-003','WEB-002')
        self.page.locator('input[name="relationship-kind"][value="parallel"]').check()
        self.apply()
        self.assertEqual(self.js("getTicket('WEB-003').parent"), self.js("getTicket('WEB-002').parent"))
        self.assertFalse(self.js("dependencies.some(e=>e.includes('WEB-002')&&e.includes('WEB-003'))"))
        self.js('validateDocument(JSON.parse(snapshot()))')

    def test_51_relationship_cycles_and_indirect_order_rejected(self):
        before = self.js('snapshot()')
        self.js("relationshipDialog('WEB-001','WEB-005')")
        self.assertEqual(self.page.locator('input[name="relationship-kind"]:disabled').count(), 3)
        self.assertTrue(self.page.locator('#edit-apply').is_disabled())
        self.page.locator('#edit-cancel').click()
        self.assertEqual(self.js('snapshot()'), before)
        self.js("relationshipDialog('WEB-005','WEB-007')")
        self.assertTrue(self.page.locator('input[value="parallel"]').is_disabled())
        self.assertIn('間接的な前後関係', self.page.locator('#edit-fields').inner_text())
        self.page.keyboard.press('Escape')
        self.assertEqual(self.js('snapshot()'), before)

    def test_52_drag_cancel_and_multi_selection_keep_move_semantics(self):
        before = self.js('snapshot()')
        self.drop_on('WEB-004','WEB-002',release=False)
        self.assertEqual(self.page.locator('.drop-target').get_attribute('data-ticket'), 'WEB-002')
        self.assertEqual(self.js('snapshot()'), before)  # Preview coordinates are never saved.
        self.page.mouse.up()
        self.page.locator('#edit-cancel').click()
        self.assertEqual(self.js('snapshot()'), before)
        self.assertEqual(self.js('undoStack.length'), 0)
        self.assertEqual(self.page.locator('.drop-target').count(), 0)
        self.drop_on('WEB-004','WEB-002',release=False)
        self.page.keyboard.press('Escape')
        self.page.mouse.up()
        self.assertFalse(self.page.locator('#edit-dialog').is_visible())
        self.assertEqual(self.js('snapshot()'), before)
        self.select('WEB-002','WEB-004')
        self.drop_on('WEB-002','WEB-003')
        self.assertFalse(self.page.locator('#edit-dialog').is_visible())
        self.assertNotEqual(self.js('snapshot()'), before)
        self.assertEqual(self.js("getTicket('WEB-002').parent"), 'WEB-001')

    def test_53_memo_drop_offers_nonblocking_reference(self):
        self.js("newMemo();document.activeElement.blur();arrange();fitBoard()")
        memo = self.js('selectedId')
        self.drop_on(memo,'WEB-002')
        self.assertTrue(self.page.locator('input[value="after"]').is_disabled())
        self.page.locator('input[value="reference"]').check()
        self.apply()
        self.assertIn([memo,'WEB-002'],self.js('references'))
        self.assertEqual(self.js('dependencies.length'), 3)


    def test_56_bottom_strips_removed_canvas_reaches_window_edge(self):
        self.assertEqual(self.page.locator('.canvas-caption,.statusbar').count(), 0)
        self.assertFalse(self.page.locator('#status-notice').is_visible())
        for width,height in [(1600,1000),(1100,800)]:
            self.page.set_viewport_size({'width':width,'height':height})
            box = self.page.locator('#canvas-scroll').bounding_box()
            self.assertAlmostEqual(box['y']+box['height'],height,delta=1)
            details = self.page.locator('.details').bounding_box()
            self.assertAlmostEqual(details['y']+details['height'],height,delta=1)
        self.page.locator('#help-button').click()
        self.assertIn('Ctrl＋Z',self.page.locator('#help-dialog').inner_text())

    def test_57_transient_notices_do_not_take_layout_space(self):
        self.page.clock.install()
        before = self.page.locator('#canvas-scroll').bounding_box()
        self.js("updateStatus('Test action result')")
        self.assertTrue(self.page.locator('#status-notice').is_visible())
        self.assertEqual(self.page.locator('#canvas-scroll').bounding_box(),before)
        self.page.locator('#dismiss-notice').click()
        self.assertFalse(self.page.locator('#status-notice').is_visible())
        self.page.locator('#help-button').click()
        self.assertEqual(self.page.locator('#guide-status').inner_text(),'Test action result')
        self.page.locator('#close-help').click()
        self.js("updateStatus('Another action')")
        self.page.clock.fast_forward(5000)
        self.assertFalse(self.page.locator('#status-notice').is_visible())
        self.js("updateStatus('Quiet autosave',false)")
        self.assertFalse(self.page.locator('#status-notice').is_visible())

    def test_58_parent_editor_inherits_project_for_subtree_only_one_undo(self):
        self.js("groups.push({id:'G-scope',name:'Unrelated grouped card',ids:['WEB-002','WEB-003']});renderAll()")
        before = self.js('snapshot()')
        self.page.locator('#parent-select').select_option('EVT-001')
        self.assertEqual(self.js("getTicket('WEB-002').parent"),'EVT-001')
        original = json.loads(before)
        after = self.js('tickets')
        for old,new in zip(original['tickets'],after):
            expected = 'event' if old['id'] in ['WEB-002','WEB-005'] else old['project']
            self.assertEqual(new['project'],expected)
            for field in ['assignee','start','due','state','x','y','description']:
                self.assertEqual(new[field],old[field])
        self.assertEqual(self.js('undoStack.length'),1)
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('snapshot()'),before)
        self.js("setParent('WEB-005',null)")
        self.assertEqual(self.js("getTicket('WEB-005').project"),'website')
        self.assertIsNone(self.js("getTicket('WEB-005').parent"))

    def test_59_cross_project_drag_child_inherits_and_undoes(self):
        self.page.locator('[data-project="all"]').click()
        before = self.js('snapshot()')
        self.drop_on('WEB-002','EVT-001')
        self.page.locator('input[value="child"]').check()
        self.apply()
        self.assertEqual(self.js("getTicket('WEB-002').parent"),'EVT-001')
        self.assertEqual(self.js("['WEB-002','WEB-005'].map(id=>getTicket(id).project)"),['event','event'])
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('snapshot()'),before)

    def test_60_parallel_inherits_project_after_and_reference_do_not(self):
        self.page.locator('[data-project="all"]').click()
        self.js("relationshipDialog('WEB-002','EVT-002')")
        self.page.locator('input[value="parallel"]').check()
        self.apply()
        self.assertEqual(self.js("getTicket('WEB-002').parent"),'EVT-001')
        self.assertEqual(self.js("getTicket('WEB-005').project"),'event')
        self.page.locator('#undo-button').click()
        self.js("relationshipDialog('WEB-002','EVT-002')")
        self.page.locator('input[value="after"]').check()
        self.apply()
        self.assertEqual(self.js("getTicket('WEB-005').project"),'website')
        self.assertEqual(self.js("getTicket('WEB-002').parent"),'WEB-001')
        before = self.js('snapshot()')
        self.js("relationshipDialog('WEB-001','WEB-005')")
        self.assertTrue(self.page.locator('#edit-apply').is_disabled())
        self.page.locator('#edit-cancel').click()
        self.assertEqual(self.js('snapshot()'),before)


    def test_62_noop_parent_choices_keep_details_bound_to_live_cards(self):
        original=self.js('snapshot()')
        self.js("setParent('WEB-002','WEB-001');relationshipDialog('WEB-005','WEB-002')")
        self.page.locator('input[value="child"]').check()
        self.apply()
        self.assertEqual(self.js('snapshot()'),original)
        self.assertEqual(self.js('undoStack.length'),0)
        self.page.locator('#detail-title').fill('Still editing the live ticket')
        self.assertEqual(self.js("getTicket('WEB-002').title"),'Still editing the live ticket')
        self.page.locator('#detail-title').press('Tab')
        self.page.locator('#undo-button').click()
        self.assertEqual(self.js('snapshot()'),original)


class WorkspacePersistence(unittest.TestCase):
    """Real browser filesystem handles on a temporary loopback test origin.

    Native Windows folder selection is checked separately by test_native_workspace.py.
    """
    js = TicketInteractions.js
    card = TicketInteractions.card
    select = TicketInteractions.select
    apply = TicketInteractions.apply
    drop_on = TicketInteractions.drop_on
    setUp = TicketInteractions.setUp
    tearDown = TicketInteractions.tearDown

    @classmethod
    def setUpClass(cls):
        TicketInteractions.setUpClass.__func__(cls)
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(Path(__file__).parent)))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/index.html'

    @classmethod
    def tearDownClass(cls):
        TicketInteractions.tearDownClass.__func__(cls)
        cls.server.shutdown()
        cls.server.server_close()

    def workspace(self):
        self.js("""async () => {
            globalThis.testRoot=await(await navigator.storage.getDirectory()).getDirectoryHandle('test-workspace',{create:true});
            await Workspace.create(testRoot);
        }""")
        self.assertEqual(self.js('Workspace.phase'), 'saved')

    def saved(self):
        self.page.wait_for_function("() => Workspace.phase==='saved' && Workspace.saved===snapshot()", timeout=12000)

    def read(self, path):
        return self.js("async path => new TextDecoder().decode(await fileBytes(testRoot,path))", path)

    def write(self, path, value):
        self.js("""async ([path,value]) => {
            const writer=await(await fileHandle(testRoot,path,true)).createWritable();
            await writer.write(value);await writer.close();
        }""", [path, value])

    def test_24_create_exact_file_roles(self):
        self.workspace()
        data=json.loads(self.read('workspace.json'))
        self.assertEqual((data['format'],data['version']),('knot-workspace',3))
        self.assertEqual(len(data['tickets']),10)
        self.assertTrue(all('description' not in t for t in data['tickets']))
        self.assertTrue(all('data' not in a for t in data['tickets'] for a in t['attachments']))
        self.assertEqual(self.read('tickets/WEB-002.md'), self.js("getTicket('WEB-002').description"))
        self.assertEqual(sum(len(t['attachments']) for t in data['tickets']),2)
        self.assertEqual(self.page.locator('#export-button,#import-input').count(),0)

    def test_25_autosave_metadata_markdown_and_reopen(self):
        self.workspace()
        self.select('WEB-002')
        self.page.fill('#detail-description','## Native Markdown\n\n- Content test\n')
        self.page.locator('#detail-description').press('Tab')
        self.page.fill('#detail-assignee','Ren')
        self.page.locator('#detail-assignee').press('Tab')
        self.saved()
        self.assertEqual(self.read('tickets/WEB-002.md'),'## Native Markdown\n\n- Content test\n')
        data=json.loads(self.read('workspace.json'))
        self.assertEqual(next(t['assignee'] for t in data['tickets'] if t['id']=='WEB-002'),'Ren')
        self.js('async () => {await Workspace.open(testRoot);}')
        self.select('WEB-002')
        self.assertEqual(self.page.input_value('#detail-description'),'## Native Markdown\n\n- Content test\n')
        self.page.reload()
        self.page.locator('#workspace-menu > summary').click()
        self.page.locator('#reopen-workspace').wait_for(state='visible')
        self.page.click('#reopen-workspace')
        self.saved()

    def test_26_external_change_prevents_overwrite(self):
        self.workspace()
        self.select('WEB-002')
        self.write('tickets/WEB-002.md','External edit.\n')
        manifest=self.read('workspace.json')
        self.page.fill('#detail-description','Unsaved app edit')
        self.page.locator('#detail-description').press('Tab')
        self.page.wait_for_function("() => Workspace.phase==='conflict'")
        self.assertEqual(self.read('tickets/WEB-002.md'),'External edit.\n')
        self.assertEqual(self.read('workspace.json'),manifest)
        self.assertEqual(self.js("getTicket('WEB-002').description"),'Unsaved app edit')
        self.js('async () => {await Workspace.open(testRoot);}')
        self.assertFalse(self.page.locator('#edit-apply').is_enabled())
        self.page.click('#use-disk-version')
        self.page.locator('#edit-dialog').wait_for(state='hidden')
        self.assertEqual(self.js("getTicket('WEB-002').description"),'External edit.\n')

    def test_27_failed_save_stops_and_recovery_is_explicit(self):
        self.workspace()
        self.select('WEB-002')
        self.js("() => {globalThis.actualPersist=persistWorkspace;globalThis.attempts=0;persistWorkspace=async()=>{attempts++;throw Error('Injected write failure');};}")
        self.page.fill('#detail-description','Recover this body')
        self.page.locator('#detail-description').press('Tab')
        self.page.wait_for_function("() => Workspace.phase==='error'")
        self.page.fill('#detail-assignee','Recover this assignee')
        self.page.locator('#detail-assignee').press('Tab')
        self.page.wait_for_timeout(600)
        self.assertEqual(self.js('attempts'),1)
        self.assertTrue(self.js('!!localStorage.getItem(Workspace.recoveryKey(Workspace.id))'))
        self.js('() => {persistWorkspace=actualPersist;}')
        self.js('async () => {await Workspace.open(testRoot);}')
        self.assertTrue(self.page.locator('#edit-dialog').is_visible())
        self.apply()
        self.page.locator('#edit-dialog').wait_for(state='hidden')
        self.saved()
        self.assertEqual(self.read('tickets/WEB-002.md'),'Recover this body')
        self.assertEqual(self.js("getTicket('WEB-002').assignee"),'Recover this assignee')
        self.assertFalse(self.js('!!localStorage.getItem(Workspace.recoveryKey(Workspace.id))'))

    def test_28_switch_workspaces_without_merging(self):
        self.workspace()
        self.select('WEB-002')
        self.page.fill('#detail-description','Workspace one')
        self.page.locator('#detail-description').press('Tab')
        self.saved()
        self.js("async()=>{globalThis.firstRoot=testRoot;globalThis.secondRoot=await(await navigator.storage.getDirectory()).getDirectoryHandle('second-workspace',{create:true});await Workspace.create(secondRoot);}")
        self.select('WEB-002')
        self.page.fill('#detail-description','Workspace two')
        self.page.locator('#detail-description').press('Tab')
        self.saved()
        self.js('async()=>{await Workspace.open(firstRoot);}')
        self.assertEqual(self.js("getTicket('WEB-002').description"),'Workspace one')
        self.js('async()=>{await Workspace.open(secondRoot);}')
        self.assertEqual(self.js("getTicket('WEB-002').description"),'Workspace two')

    def test_29_bad_paths_and_format_leave_document_intact(self):
        self.workspace()
        before=self.js('snapshot()')
        original=json.loads(self.read('workspace.json'))
        invalid=json.loads(json.dumps(original))
        invalid['tickets'][0]['content_file']='../outside.md'
        self.write('workspace.json',json.dumps(invalid))
        result=self.js('async()=>{try{await Workspace.open(testRoot);return false;}catch(e){return true;}}')
        self.assertTrue(result)
        self.assertEqual(self.js('snapshot()'),before)
        invalid['version']=99
        self.write('workspace.json',json.dumps(invalid))
        self.assertTrue(self.js('async()=>{try{await Workspace.open(testRoot);return false;}catch(e){return true;}}'))
        self.assertEqual(self.js('snapshot()'),before)

    def test_30_empty_folder_confirmation_and_nonempty_refusal(self):
        self.js("async()=>{globalThis.testRoot=await(await navigator.storage.getDirectory()).getDirectoryHandle('new-empty',{create:true});await Workspace.open(testRoot);}")
        self.assertTrue(self.page.locator('#edit-dialog').is_visible())
        self.assertIsNone(self.js("async()=>hashOnDisk(testRoot,'workspace.json')"))
        self.page.click('#edit-cancel')
        self.assertIsNone(self.js("async()=>hashOnDisk(testRoot,'workspace.json')"))
        self.write('tickets/orphan.md','Keep existing file')
        self.assertTrue(self.js('async()=>{try{await Workspace.open(testRoot);return false;}catch(e){return true;}}'))
        self.assertEqual(self.read('tickets/orphan.md'),'Keep existing file')

    def test_31_picker_cancel_and_permission_denial_preserve_state(self):
        before=self.js('snapshot()')
        self.js("() => {window.showDirectoryPicker=async()=>{throw new DOMException('cancelled','AbortError');};}")
        self.page.locator('#workspace-menu > summary').click()
        self.page.click('#open-workspace')
        self.assertEqual(self.js('snapshot()'),before)
        self.js("() => {Workspace.recent={name:'permission-test',queryPermission:async()=> 'prompt',requestPermission:async()=> 'denied'};Workspace.render();}")
        self.page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
        self.page.click('#reopen-workspace')
        self.assertIsNone(self.js('Workspace.handle'))
        self.assertEqual(self.js('snapshot()'),before)

    def test_32_attachments_folding_and_undo_persist(self):
        self.workspace()
        self.select('WEB-002')
        self.page.locator('#attachment-input').set_input_files({'name':'note.txt','mimeType':'text/plain','buffer':b'actual file bytes'})
        self.page.wait_for_function("()=>getTicket('WEB-002').attachments.length===2")
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.saved()
        metadata=json.loads(self.read('workspace.json'))
        entry=next(t for t in metadata['tickets'] if t['id']=='WEB-002')
        attachment=next(a for a in entry['attachments'] if a['name']=='note.txt')
        self.assertEqual(self.read(attachment['file']),'actual file bytes')
        self.js('async()=>{await Workspace.open(testRoot);}')
        self.assertTrue(self.js("collapsed.has('WEB-002')"))
        self.page.locator('[data-collapse="WEB-002"]').click()
        self.saved()
        self.page.locator('#undo-button').click()
        self.saved()
        self.assertIn('WEB-002',json.loads(self.read('workspace.json'))['collapsed'])

    def test_33_retry_after_write_failure(self):
        self.workspace()
        self.select('WEB-002')
        self.js("()=>{globalThis.actualPersist=persistWorkspace;persistWorkspace=async()=>{throw Error('Injected failure');};}")
        self.page.fill('#detail-description','Retry saved content')
        self.page.locator('#detail-description').press('Tab')
        self.page.wait_for_function("()=>Workspace.phase==='error'")
        self.js('()=>{persistWorkspace=actualPersist;}')
        self.page.locator('#workspace-menu').evaluate('(el)=>el.open=true')
        self.page.click('#save-workspace')
        self.saved()
        self.assertEqual(self.read('tickets/WEB-002.md'),'Retry saved content')

    def test_34_edits_during_save_are_serialized(self):
        self.workspace()
        self.select('WEB-002')
        self.js("""()=>{
         globalThis.actualPersist=persistWorkspace;globalThis.pauseNext=true;
         persistWorkspace=async(...args)=>{if(pauseNext){pauseNext=false;globalThis.waiting=true;await new Promise(resolve=>globalThis.releaseSave=resolve);}return actualPersist(...args);};
        }""")
        self.page.fill('#detail-description','First body')
        self.page.locator('#detail-description').press('Tab')
        self.page.wait_for_function('()=>globalThis.waiting')
        self.assertNotEqual(self.page.locator('#workspace-state').get_attribute('data-state'),'saved')
        self.page.fill('#detail-description','Second body')
        self.page.locator('#detail-description').press('Tab')
        self.js('()=>{releaseSave();}')
        self.saved()
        self.assertEqual(self.read('tickets/WEB-002.md'),'Second body')

    def test_35_deleted_notes_are_retained_for_recovery(self):
        self.workspace()
        self.select('WEB-002')
        self.card('WEB-002').click(button='right')
        self.page.click('[data-action="delete"]')
        self.apply()
        self.saved()
        self.assertIsNotNone(self.js("async()=>hashOnDisk(testRoot,'tickets/WEB-002.md')"))
        self.assertNotIn('WEB-002',[t['id'] for t in json.loads(self.read('workspace.json'))['tickets']])
        self.page.locator('#undo-button').click()
        self.saved()
        self.assertIn('WEB-002',[t['id'] for t in json.loads(self.read('workspace.json'))['tickets']])

    def test_36_unreadable_size_and_duplicate_ids_rejected_before_writing(self):
        self.workspace()
        before=self.read('workspace.json')
        self.assertTrue(self.js("""async()=>{
         const data=JSON.parse(snapshot());data.tickets[0].description='x'.repeat(16*1024*1024+1);
         try{await persistWorkspace(testRoot,Workspace,data);return false;}catch(e){return true;}
        }"""))
        self.assertEqual(self.read('workspace.json'),before)
        self.assertTrue(self.js("""()=>{
         const data=JSON.parse(snapshot()),t=data.tickets.find(t=>t.attachments.length);
         t.attachments.push({...t.attachments[0]});
         try{validateDocument(data);return false;}catch(e){return true;}
        }"""))


    def test_43_memo_markdown_references_and_states_roundtrip(self):
        self.workspace()
        self.js("newMemo('WEB-002')")
        memo=self.js('selectedId')
        self.page.locator('#detail-description').fill('Reference memo\nWith two lines')
        self.page.locator('#detail-description').press('Tab')
        self.saved()
        manifest=json.loads(self.read('workspace.json'))
        entry=next(t for t in manifest['tickets'] if t['id']==memo)
        self.assertEqual(entry['state'], 'メモ')
        self.assertEqual(entry['due'], '')
        self.assertIn(['WEB-002',memo],manifest['references'])
        self.assertEqual(self.read(entry['content_file']), 'Reference memo\nWith two lines')
        self.js('tickets.length=0;references=[];selected.clear();selectedId=null')
        self.js('async()=>Workspace.adopt(testRoot,await readWorkspace(testRoot))')
        self.assertEqual(self.js('getTicket('+json.dumps(memo)+').description'), 'Reference memo\nWith two lines')
        self.assertEqual(self.js('references'), [['WEB-002',memo]])
        self.js('selectTicket('+json.dumps(memo)+')')
        self.page.locator('#detail-state').select_option('非実施')
        self.saved()
        self.assertEqual(next(t for t in json.loads(self.read('workspace.json'))['tickets'] if t['id']==memo)['state'], '非実施')


    def test_54_drag_preview_not_written_by_pending_autosave(self):
        self.workspace()
        before = self.js('tickets.map(({id,x,y})=>({id,x,y}))')
        self.select('WEB-002')
        self.page.locator('#detail-description').fill('Save body, not drag preview')
        self.page.locator('#detail-description').press('Tab')
        self.drop_on('WEB-002','WEB-004',release=False)
        self.saved()
        on_disk = [{key:t[key] for key in ('id','x','y')} for t in json.loads(self.read('workspace.json'))['tickets']]
        self.assertEqual(on_disk, before)
        self.page.mouse.up()
        self.page.locator('#edit-cancel').click()
        self.assertEqual(self.js('tickets.map(({id,x,y})=>({id,x,y}))'),before)
        self.assertEqual(self.read('tickets/WEB-002.md'), 'Save body, not drag preview')

    def test_55_drop_relationship_persists_and_undo_restores(self):
        self.workspace()
        original = self.js('clone(dependencies)')
        self.drop_on('WEB-002','WEB-003')
        self.page.locator('input[value="after"]').check()
        self.apply()
        self.saved()
        stored = json.loads(self.read('workspace.json'))
        self.assertIn(['WEB-003','WEB-002'],stored['dependencies'])
        self.assertNotIn(['WEB-002','WEB-003'],stored['dependencies'])
        self.page.locator('#undo-button').click()
        self.saved()
        self.assertEqual(json.loads(self.read('workspace.json'))['dependencies'],original)
        self.page.locator('#redo-button').click()
        self.saved()
        self.js('async()=>Workspace.adopt(testRoot,await readWorkspace(testRoot))')
        self.assertIn(['WEB-003','WEB-002'],self.js('dependencies'))


    def test_61_parent_subtree_projects_persist_and_restore_in_one_undo(self):
        self.workspace()
        self.select('WEB-002')
        original = self.js('clone(tickets)')
        self.page.locator('#parent-select').select_option('EVT-001')
        self.saved()
        data=json.loads(self.read('workspace.json'))
        self.assertEqual([t['project'] for t in data['tickets'] if t['id'] in ['WEB-002','WEB-005']],['event','event'])
        self.assertEqual(self.read('tickets/WEB-005.md'),next(t['description'] for t in original if t['id']=='WEB-005'))
        self.assertEqual(self.js('undoStack.length'),1)
        self.page.locator('#undo-button').click()
        self.saved()
        self.assertEqual(self.js('tickets'),original)
        self.assertEqual([t['project'] for t in json.loads(self.read('workspace.json'))['tickets'] if t['id'] in ['WEB-002','WEB-005']],['website','website'])


if __name__ == "__main__":
    unittest.main(verbosity=2)
