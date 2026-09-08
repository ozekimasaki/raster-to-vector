"""Offline behavioral tests. python -m unittest discover -s tests -v"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import numpy as np
from PIL import Image, ImageCms
from r2v_lib.images import analyze, compare, load_image, propose
from r2v_lib.mosaic.compose import compose_svg, reversal_pairs_match, shared_boundary_json, shared_coord_text
from r2v_lib.mosaic.faces import area_matches_pixels, build_from_labels, rasterize_faces
from r2v_lib.mosaic.fit import fit_graph, oriented
from r2v_lib.mosaic.graph import contour_points
from r2v_lib.svg import inspect, path_segments
from r2v_lib.render import render


class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r2v 日本語 space ')
        self.dir = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def png(self, name, color=(200,30,70,255), size=(16,16)):
        p = self.dir/name; Image.new('RGBA', size, color).save(p); return p

    def svg(self, body, attrs='width="16" height="16" viewBox="0 0 16 16"'):
        p = self.dir/'test.svg'; p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>', encoding='utf-8'); return p

    def test_identity_premultiplied_metrics(self):
        a = self.png('a.png'); result = compare(a,a,self.dir/'compare')
        self.assertEqual(result['metrics']['premultiplied_rgb_max'],0)
        self.assertEqual(result['quality_status'],'indeterminate')

    def test_transparent_hidden_rgb_ignored(self):
        a=self.png('a.png',(255,0,0,0)); b=self.png('b.png',(0,255,0,0))
        result=compare(a,b,self.dir/'compare')
        self.assertEqual(result['metrics']['premultiplied_rgb_max'],0)
        self.assertIsNone(result['metrics']['silhouette_iou'])

    def test_alpha_deficit_and_excess(self):
        a=self.png('a.png',(200,30,70,128)); b=self.png('b.png',(200,30,70,255))
        r=compare(a,b,self.dir/'c')['metrics']
        self.assertGreater(r['alpha_max_excess'],.49)
        self.assertEqual(r['alpha_max_deficit'],0)

    def test_wrong_color_not_hidden_by_alpha(self):
        a=self.png('a.png'); b=self.png('b.png',(0,255,0,255))
        r=compare(a,b,self.dir/'c')['metrics']
        self.assertEqual(r['alpha_mae'],0); self.assertGreater(r['premultiplied_rgb_max'],.8)

    def test_size_mismatch_not_rescaled(self):
        a=self.png('a.png'); b=self.png('b.png',size=(8,8))
        with self.assertRaises(ValueError): compare(a,b,self.dir/'c')

    def test_quantization_preserves_alpha_and_holes(self):
        a=np.zeros((16,16,4),dtype=np.uint8); a[:,:,:3]=[80,120,170]; a[:,:,3]=np.arange(16)*17
        p=self.dir/'a.png'; Image.fromarray(a).save(p)
        propose(p,self.dir/'q',8)
        q=np.asarray(Image.open(self.dir/'q/regions.png'))
        np.testing.assert_array_equal(q[:,:,3],a[:,:,3])
        labels=np.load(self.dir/'q/labels.npy',allow_pickle=False)
        self.assertTrue((labels[:,0]==-1).all())

    def test_fully_transparent_regions(self):
        r=propose(self.png('a.png',(1,2,3,0)),self.dir/'q',32)
        self.assertEqual(r['palette_rgb'],[])

    def test_exif_orientation(self):
        p=self.dir/'exif.jpg'; exif=Image.Exif(); exif[274]=6
        Image.new('RGB',(10,20)).save(p,exif=exif)
        im,meta=load_image(p); self.assertEqual(im.size,(20,10)); self.assertEqual(meta['exif_orientation'],6)

    def test_valid_and_invalid_icc(self):
        p=self.dir/'icc.png'; icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB',(4,4)).save(p,icc_profile=icc)
        self.assertEqual(load_image(p)[1]['color_management'],'ICC_converted_to_sRGB')
        Image.new('RGB',(4,4)).save(p,icc_profile=b'not-an-icc')
        with self.assertRaises(ValueError): load_image(p)

    def test_multiframe_requires_choice(self):
        p=self.dir/'anim.webp'
        Image.new('RGB',(8,8),'red').save(p,save_all=True,append_images=[Image.new('RGB',(8,8),'blue')],duration=100,loop=0)
        with self.assertRaises(ValueError): load_image(p)
        self.assertEqual(load_image(p,1)[1]['frame'],1)

    def test_corrupt_image_cli(self):
        p=self.dir/'bad.png'; p.write_bytes(b'bad')
        r=subprocess.run([sys.executable,str(ROOT/'scripts/r2v.py'),'analyze',str(p),'--out',str(self.dir/'out')],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(r.returncode,2); self.assertEqual(json.loads(r.stdout)['status'],'failed')

    def test_safe_gradient_clip(self):
        p=self.svg('<defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient><clipPath id="c"><circle cx="8" cy="8" r="5"/></clipPath></defs><rect width="16" height="16" fill="url(#g)" clip-path="url(#c)"/>')
        self.assertEqual(inspect(p)[0]['status'],'passed')

    def test_crisp_aa_fixture_inspects_without_use(self):
        for name in ('two_rects_normal','two_rects_base_fill','two_rects_crisp_aa'):
            status=inspect(ROOT/f'examples/fixtures/{name}.svg')[0]['status']
            self.assertEqual(status,'passed',name)
        self.assertEqual(inspect(self.svg('<defs><g id="faces"><rect width="8" height="8"/></g></defs><use href="#faces"/>'))[0]['status'],'failed')

    def test_inert_cfvx_metadata(self):
        p=self.svg('<g data-cfvx-role="fill"><path d="M0 0L1 1Z"/></g>')
        self.assertEqual(inspect(p)[0]['status'],'passed')

    def test_external_and_active_svg_rejected(self):
        cases=['<script>alert(1)</script>','<image href="data:image/png;base64,AA=="/>',
               '<foreignObject/>','<use href="#x"/>','<rect onload="alert(1)"/>',
               '<style>@import "https://example.com";</style>', '<rect fill="url(https://example.com/a)"/>',
               '<rect style="fill:u\\72l(https://example.com)"/>','<rect style="fill:var(--paint)"/>',
               '<rect style="cursor:url(file:///secret)"/>']
        for body in cases:
            with self.subTest(body=body): self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')

    def test_duplicate_missing_wrong_reference(self):
        for body in ['<g id="x"/><g id="x"/>','<rect fill="url(#missing)"/>','<g id="x"/><rect fill="url(#x)"/>']:
            self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')

    def test_numeric_path_rejections(self):
        for body in ['<path d="M 0 0 L 1"/>','<path d="M 0 0 A 1 1 0 3 0 2 2"/>','<rect width="NaN"/>','<circle r="-1"/>']:
            self.assertEqual(inspect(self.svg(body))[0]['status'],'failed')
        self.assertEqual(path_segments('M0 0C1 2 3 4 5 6Z'),3)

    def test_dtd_rejected(self):
        p=self.dir/'entity.svg'; p.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///test">]><svg/>')
        self.assertEqual(inspect(p)[0]['status'],'failed')

    def test_topology_not_certified(self):
        r,_=inspect(self.svg('<path d="M0 0L16 16L0 16L16 0Z"/>'))
        self.assertEqual(r['status'],'passed'); self.assertEqual(r['topology'],'indeterminate')

    def test_no_renderer_preserves_indeterminate(self):
        p=self.svg('<rect width="16" height="16"/>')
        failure=subprocess.CompletedProcess([],3,'{"error":"missing"}','')
        with patch('r2v_lib.render.run_bounded',return_value=failure):
            with self.assertRaises(RuntimeError): render(p,self.dir/'r')
        self.assertEqual(json.loads((self.dir/'r/render.json').read_text())['status'],'indeterminate')

    def test_chromium_failure_falls_back_with_evidence(self):
        p=self.svg('<rect width="16" height="16"/>')
        first=subprocess.CompletedProcess([],3,'missing','')
        second=subprocess.CompletedProcess([],0,'{"status":"passed","renderer":"cairosvg"}','')
        with patch('r2v_lib.render.run_bounded',side_effect=[first,second]): result=render(p,self.dir/'r')
        self.assertEqual(result['renderer'],'cairosvg'); self.assertEqual(len(result['failed_attempts']),1)

    def test_chromium_only(self):
        p=self.svg('<rect width="16" height="16"/>')
        success=subprocess.CompletedProcess([],0,'{"status":"passed","renderer":"chromium"}','')
        with patch('r2v_lib.render.run_bounded',return_value=success) as call: result=render(p,self.dir/'r')
        self.assertEqual(result['renderer'],'chromium'); self.assertEqual(call.call_count,1)

    def test_worker_timeout(self):
        from r2v_lib.processes import run_bounded
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable,'-c','import time; time.sleep(10)'],timeout=.2)


class Mosaic(unittest.TestCase):
    def check_map(self, labels, *, nodes=None, segments=None, rings=None):
        labels = np.asarray(labels, dtype=np.int32)
        graph, faces = build_from_labels(labels)
        self.assertTrue(area_matches_pixels(graph, faces, labels))
        recon = rasterize_faces(graph, faces)
        np.testing.assert_array_equal(recon, labels)
        if nodes is not None:
            self.assertEqual(len(graph.nodes), nodes)
        if segments is not None:
            self.assertEqual(len(graph.segments), segments)
        if rings is not None:
            self.assertEqual(sum(1 for seg in graph.segments if seg.is_ring), rings)
        fitted = fit_graph(graph, 'pixel')
        self.assertTrue(reversal_pairs_match(graph, faces, fitted))
        return graph, faces, fitted

    def test_single_pixel_ring(self):
        graph, faces, _ = self.check_map([[0]], nodes=0, segments=1, rings=1)
        self.assertEqual(list(faces), [0])

    def test_full_image_ring(self):
        self.check_map([[0, 0], [0, 0]], nodes=0, segments=1, rings=1)

    def test_vertical_split(self):
        graph, faces, fitted = self.check_map([[0, 1]], nodes=2, segments=3, rings=0)
        shared = [i for i, seg in enumerate(graph.segments) if {seg.left, seg.right} == {0, 1}]
        self.assertEqual(len(shared), 1)
        sid = shared[0]
        self.assertEqual(shared_coord_text(fitted[sid], True), '1 0 1 1')
        self.assertEqual(shared_coord_text(fitted[sid], False), '1 1 1 0')
        self.assertEqual(shared_coord_text(oriented(fitted[sid], False), True), '1 1 1 0')

    def test_t_junction(self):
        graph, faces, _ = self.check_map([[0, 0], [1, 2]])
        interior = [n for n in graph.nodes if (n.x, n.y) == (1, 1)]
        self.assertEqual(len(interior), 1)
        self.assertEqual(set(faces), {0, 1, 2})

    def test_checkerboard_pinch(self):
        graph, faces, _ = self.check_map([[0, 1], [1, 0]])
        pinch = [n for n in graph.nodes if (n.x, n.y) == (1, 1)]
        self.assertEqual(len(pinch), 1)
        self.assertEqual(sum(1 for d in pinch[0].out if d is not None), 4)
        for region, contours in faces.items():
            pts = contour_points(graph, contours[0])
            self.assertGreaterEqual(pts.count((1, 1)), 2)

    def test_nested_rings(self):
        labels = [
            [0, 0, 0, 0, 0],
            [0, 1, 1, 1, 0],
            [0, 1, 2, 1, 0],
            [0, 1, 1, 1, 0],
            [0, 0, 0, 0, 0],
        ]
        graph, faces, fitted = self.check_map(labels, nodes=0, segments=3, rings=3)
        self.assertEqual(len(faces[0]), 2)
        self.assertEqual(len(faces[1]), 2)
        self.assertEqual(len(faces[2]), 1)
        hole = graph.segments[2]
        self.assertEqual(shared_coord_text(fitted[2], True), shared_coord_text(oriented(fitted[2], False), False))
        self.assertNotEqual(hole.left, hole.right)

    def test_border_touching_and_corridor(self):
        self.check_map([[-1, 0, 0], [-1, 0, -1]], rings=1)
        self.check_map([
            [0, 0, 0, 0],
            [0, 1, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 0],
        ])

    def test_polygon_keeps_endpoints(self):
        labels = np.array([[0, 1, 1], [0, 0, 1]], dtype=np.int32)
        graph, faces = build_from_labels(labels)
        fitted = fit_graph(graph, 'polygon', 0.5)
        for seg, geom in zip(graph.segments, fitted):
            if seg.is_ring:
                continue
            self.assertEqual(geom.start, (float(seg.points[0][0]), float(seg.points[0][1])))
            self.assertEqual(geom.end, (float(seg.points[-1][0]), float(seg.points[-1][1])))
        self.assertTrue(reversal_pairs_match(graph, faces, fitted))

    def test_svg_shared_numbers_and_inspect(self):
        labels = np.array([[0, 1]], dtype=np.int32)
        graph, faces, fitted = self.check_map(labels)
        svg = compose_svg(graph, faces, fitted, {0: (196, 53, 77, 255), 1: (36, 105, 200, 255)})
        self.assertIn('fill-rule="nonzero"', svg)
        self.assertIn('L1 1', svg)
        self.assertIn('L1 0', svg)
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / 'm.svg'
        path.write_text(svg, encoding='utf-8')
        self.assertEqual(inspect(str(path))[0]['status'], 'passed')
        payload = shared_boundary_json(graph, faces, fitted, {0: (196, 53, 77), 1: (36, 105, 200)})
        edge = next(v for v in payload['edges'].values() if {v['left'], v['right']} == {0, 1})
        self.assertEqual(edge['forward_d'], 'M1 0L1 1')
        self.assertEqual(edge['reverse_d'], 'M1 1L1 0')
        temp.cleanup()

    def test_cli_pixel_round_trip(self):
        temp = tempfile.TemporaryDirectory(prefix='mosaic ')
        folder = Path(temp.name)
        src = folder / 'in.png'
        arr = np.zeros((4, 6, 4), dtype=np.uint8)
        arr[:, :, :3] = (40, 80, 120)
        arr[:, :, 3] = 255
        arr[:, 3:, :3] = (200, 30, 70)
        Image.fromarray(arr).save(src)
        labels = np.zeros((4, 6), dtype=np.int32)
        labels[:, 3:] = 1
        np.save(folder / 'labels.npy', labels)
        out = folder / 'out'
        run = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/r2v.py'), 'mosaic-draft', str(src),
             '--out', str(out), '--from-labels', str(folder / 'labels.npy'), '--mode', 'pixel'],
            capture_output=True, text=True, encoding='utf-8',
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        status = json.loads(run.stdout)
        self.assertEqual(status['status'], 'draft_only')
        self.assertEqual(status['quality_status'], 'indeterminate')
        self.assertTrue(status['pixel_round_trip'])
        self.assertTrue(status['area_matches_pixels'])
        self.assertTrue((out / 'candidate.svg').is_file())
        self.assertTrue((out / 'shared-boundary.json').is_file())
        self.assertEqual(inspect(str(out / 'candidate.svg'))[0]['status'], 'passed')
        temp.cleanup()

    def test_curve_mode_pins_and_inspects(self):
        labels = np.zeros((8, 8), dtype=np.int32)
        yy, xx = np.ogrid[:8, :8]
        labels[(xx - 3.5) ** 2 + (yy - 3.5) ** 2 <= 9] = 1
        graph, faces = build_from_labels(labels)
        fitted = fit_graph(graph, 'curve', 0.5)
        for seg, geom in zip(graph.segments, fitted):
            if seg.is_ring:
                continue
            self.assertEqual(geom.start, (float(seg.points[0][0]), float(seg.points[0][1])))
            self.assertEqual(geom.end, (float(seg.points[-1][0]), float(seg.points[-1][1])))
        self.assertTrue(reversal_pairs_match(graph, faces, fitted))
        svg = compose_svg(graph, faces, fitted, {0: (200, 200, 200, 255), 1: (30, 80, 180, 255)})
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / 'c.svg'
        path.write_text(svg, encoding='utf-8')
        self.assertEqual(inspect(str(path))[0]['status'], 'passed')
        temp.cleanup()


if __name__=='__main__': unittest.main()
