import networkx as nx
from maker import extract_network
from config import configure
from evaluation import Evaluation
from itertools import islice
from Mine.nodemdp import NodeEnv
from Mine.linkmdp import LinkEnv
from Mine.linkrf import nodepolicy
from Mine.linkrf import linkpolicy
import copy


def calculate_adjacent_bw(graph, u, kind='bw'):
    """计算一个节点的相邻链路带宽和，默认为总带宽和，若计算剩余带宽资源和，需指定kind属性为bw-remain"""

    bw_sum = 0
    for v in graph.neighbors(u):
        bw_sum += graph[u][v][kind]
    return bw_sum


# k最短路径
def k_shortest_path(G, source, target, k=5):
    return list(islice(nx.shortest_simple_paths(G, source, target), k))


class Substrate:

    def __init__(self, path, filename):
        self.net = extract_network(path, filename)
        self.agent = None
        self.mapped_info = {}
        self.evaluation = Evaluation(self.net)
        self.no_solution = False

    def set_topology(self, graph):
        self.net = graph

    def handle(self, queue, algorithm, arg=0):

        # self.linkenv = LinkEnv(self.net)

        for req in queue:

            # the id of current request
            req_id = req.graph['id']

            if req.graph['type'] == 0:
                """a request which is newly arrived"""

                print("\nTry to map request%s: " % req_id)
                if self.mapping(req, algorithm, arg):
                    print("Success!")

            if req.graph['type'] == 1:
                """a request which is ready to leave"""

                if req_id in self.mapped_info.keys():
                    print("\nRelease the resources which are occupied by request%s" % req_id)
                    self.change_resource(req, 'release')

    def mapping(self, vnr, algorithm, arg):
        """two phrases:node mapping and link mapping"""

        self.evaluation.total_arrived += 1

        # mapping virtual nodes
        node_map = self.node_mapping(vnr, algorithm, arg)

        if len(node_map) == vnr.number_of_nodes():
            # mapping virtual links
            print("link mapping...")
            link_map = self.link_mapping(vnr, node_map, algorithm, arg)
            if len(link_map) == vnr.number_of_edges():
                self.mapped_info.update({vnr.graph['id']: (node_map, link_map)})
                self.change_resource(vnr, 'allocate')
                print("Success!")
                return True
            else:
                print("Failed to map all links!")
                return False
        else:
            print("Failed to map all nodes!")
            return False

    def node_mapping(self, vnr, algorithm, arg):
        """求解节点映射问题"""

        print("node mapping...")

        node_map = {}
        # 如果刚开始映射，那么需要对所选用的算法进行配置
        if algorithm != 'RLNL':
            if self.agent is None:
                self.agent = configure(self, algorithm, arg)
            node_map = self.agent.run(self, vnr)

        else:
            nodeenv = NodeEnv(self.net)
            nodeenv.set_vnr(vnr)
            nodep = nodepolicy(nodeenv.action_space.n, nodeenv.observation_space.shape)
            nodeobservation = nodeenv.reset()
            for vn_id in range(vnr.number_of_nodes()):
                sn_id = nodep.choose_max_action(nodeobservation, nodeenv.sub,
                                                vnr.nodes[vn_id]['cpu'],
                                                vnr.number_of_nodes())
                if sn_id == -1:
                    break
                else:
                    # 执行一次action，获取返回的四个数据
                    nodeobservation, _, done, info = nodeenv.step(sn_id)
                    node_map.update({vn_id: sn_id})

        # 使用指定的算法进行节点映射并得到节点映射集合

        # 返回节点映射集合
        return node_map

    def link_mapping(self, vnr, node_map, algorithm, arg):
        """求解链路映射问题"""

        link_map = {}

        if algorithm == 'grc':
            sub_copy1 = copy.deepcopy(self.net)
            for vLink in vnr.edges:
                vn_from, vn_to = vLink[0], vLink[1]
                resource = vnr[vn_from][vn_to]['bw']
                # 剪枝操作，先暂时将那些不满足当前待映射虚拟链路资源需求的底层链路删除
                sub_tmp = copy.deepcopy(sub_copy1)
                sub_edges = []
                for sLink in sub_tmp.edges:
                    sub_edges.append(sLink)
                for edge in sub_edges:
                    sn_from, sn_to = edge[0], edge[1]
                    if sub_tmp[sn_from][sn_to]['bw_remain'] <= resource:
                        sub_tmp.remove_edge(sn_from, sn_to)

                # 在剪枝后的底层网络上寻找一条可映射的最短路径
                sn_from, sn_to = node_map[vn_from], node_map[vn_to]
                if nx.has_path(sub_tmp, source=sn_from, target=sn_to):
                    path = k_shortest_path(sub_tmp, sn_from, sn_to, 1)[0]
                    link_map.update({vLink: path})

                    # 这里的资源分配是暂时的
                    start = path[0]
                    for end in path[1:]:
                        bw_tmp = sub_copy1[start][end]['bw_remain'] - resource
                        sub_copy1[start][end]['bw_remain'] = round(bw_tmp, 6)
                        start = end
                else:
                    break

            # 返回链路映射集合

            return link_map

        if algorithm == 'RLNL':
            if self.agent is None:
                self.agent = configure(self, algorithm, arg)
            # link_map = self.agent.run(self, vnr, node_map, self.linkenv)

            # linkenv = LinkEnv(self.net)
            # linkenv.set_vnr(vnr)
            # linkp = linkpolicy(linkenv.action_space.n, linkenv.observation_space.shape)
            # linkob = linkenv.reset()
            # for link in vnr.edges:
            #     linkenv.set_link(link)
            #     vn_from = link[0]
            #     vn_to = link[1]
            #     sn_from = node_map[vn_from]
            #     sn_to = node_map[vn_to]
            #     bw = vnr[vn_from][vn_to]['bw']
            #     if nx.has_path(linkenv.sub, sn_from, sn_to):
            #         linkaction = linkp.choose_max_action(linkob, linkenv.sub, bw, linkenv.linkpath, sn_from, sn_to)
            #         if linkaction == -1:
            #             break
            #         else:
            #             linkob, linkreward, linkdone, linkinfo = linkenv.step(linkaction)
            #             path = list(linkenv.linkpath[linkaction].values())[0]
            #             link_map.update({link: path})

        else:
            for vLink in vnr.edges:
                vn_from = vLink[0]
                vn_to = vLink[1]
                sn_from = node_map[vn_from]
                sn_to = node_map[vn_to]
                if nx.has_path(self.net, source=sn_from, target=sn_to):
                    for path in nx.all_shortest_paths(self.net, sn_from, sn_to):
                        if self.get_path_capacity(path) >= vnr[vn_from][vn_to]['bw']:
                            link_map.update({vLink: path})
                            break
                        else:
                            continue


        # 返回链路映射集合
        return link_map

    def change_resource(self, req, instruction):
        """分配或释放节点和链路资源"""

        # 读取该虚拟网络请求的映射信息
        req_id = req.graph['id']
        node_map = self.mapped_info[req_id][0]
        link_map = self.mapped_info[req_id][1]

        factor = -1
        if instruction == 'release':
            factor = 1

        # 分配或释放节点资源
        for v_id, s_id in node_map.items():
            self.net.nodes[s_id]['cpu_remain'] += factor * req.nodes[v_id]['cpu']

        # 分配或释放链路资源
        for vl, path in link_map.items():
            link_resource = req[vl[0]][vl[1]]['bw']
            start = path[0]
            for end in path[1:]:
                self.net[start][end]['bw_remain'] += factor * link_resource
                start = end

        if instruction == 'allocate':
            # 增加实验结果
            self.evaluation.add(req, link_map)

        if instruction == 'release':
            # 移除相应的映射信息
            self.mapped_info.pop(req_id)

    def get_path_capacity(self, path):
        """找到一条路径中带宽资源最小的链路并返回其带宽资源值"""

        bandwidth = 1000
        head = path[0]
        for tail in path[1:]:
            if self.net[head][tail]['bw_remain'] <= bandwidth:
                bandwidth = self.net[head][tail]['bw_remain']
            head = tail
        return bandwidth
